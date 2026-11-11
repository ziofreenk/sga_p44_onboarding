/* =====================================================================
   Estrazione sub-vettori FERCAM da invitare su project44 (POC #4)
   - Una riga per vettore (T2BaseVettori) usato negli ultimi 3 mesi su viaggi dei reparti FMI
   - Solo lettura. Compatibilità DB < 140: niente STRING_AGG / TRY_CAST / TRIM
   - Conteggio per esito eseguito l'11/11/2026 (vedi docs/STATO.md)
   ===================================================================== */

DECLARE @Societa        smallint    = 1;
DECLARE @DataDa         datetime    = DATEADD(MONTH, -3, CAST(GETDATE() AS date));  -- incluso: ultimi 3 mesi
DECLARE @DataA          datetime    = CAST(GETDATE() AS date);                      -- escluso
DECLARE @MinViaggi      int         = 1;      -- soglia minima viaggi nel periodo
DECLARE @TipoPOC        varchar(2)  = '01';   -- tipo interlocutore preferito: 01 = Generico (decisione 11/11/2026)
DECLARE @PivaFercam     varchar(11) = '00098090210';  -- escluso: FERCAM stessa (infragruppo)
DECLARE @NominativoDefault nvarchar(50) = N'Ufficio Traffico';  -- POC senza nome (decisione 11/11/2026)

WITH
/* 0. Reparti FMI (codice REPARTO a 3 caratteri), elenco fornito da Francesco l'11/11/2026.
      Lista esplicita, senza tabelle temporanee (lo strumento MCP ammette solo SELECT). */
RepartiFMI AS (
    SELECT r.REPARTO
    FROM  (VALUES ('BF1'),('BO2'),('BZ6'),('CB1'),('CE2'),('CF2'),('F31'),('FI1'),('G11'),('G22'),
                  ('G92'),('GE1'),('PC1'),('SL3'),('TN1'),('TN2'),('TO2'),('VN3')
          ) AS r(REPARTO)
),
/* 1. Vettori con viaggi FMI nel periodo (pre-aggregato: una riga per vettore) */
ViaggiPeriodo AS (
    SELECT  vv.SOCIETA,
            vv.VETTORE,
            COUNT(*)        AS N_VIAGGI,
            MAX(vv.DATA)    AS ULTIMO_VIAGGIO,
            COUNT(DISTINCT vv.REPARTO) AS N_REPARTI_FMI
    FROM    dbo.T2ViaggiVettori vv
    JOIN    RepartiFMI rf ON rf.REPARTO = vv.REPARTO     -- filtro reparti FMI
    WHERE   vv.SOCIETA = @Societa
      AND   vv.DATA >= @DataDa AND vv.DATA < @DataA
      AND   vv.VETTORE IS NOT NULL
      -- Nessun filtro sui viaggi annullati (decisione 11/11/2026)
    GROUP BY vv.SOCIETA, vv.VETTORE
    HAVING  COUNT(*) >= @MinViaggi
),
/* 3. Anagrafica vettore + fornitore + POC (priorità: interlocutore > testata vettore > BaCliFor) */
Base AS (
    SELECT  v.SOCIETA,
            v.CODICE                                    AS CODICE_VETTORE,
            LTRIM(RTRIM(COALESCE(cf.RAGIONE_SOCIALE, v.RAGIONE_SOCIALE))) AS RAGIONE_SOCIALE,
            UPPER(LTRIM(RTRIM(COALESCE(cf.NAZIONE, v.NAZIONE))))          AS NAZIONE,
            UPPER(REPLACE(LTRIM(RTRIM(cf.PARTITA_IVA)), ' ', ''))        AS PARTITA_IVA,
            UPPER(LTRIM(RTRIM(cf.CODICE_FISCALE)))                       AS CODICE_FISCALE,
            CASE WHEN i.E_MAIL IS NOT NULL                     THEN i.E_MAIL
                 WHEN v.E_MAIL  LIKE '%_@_%._%'                THEN LTRIM(RTRIM(v.E_MAIL))
                 WHEN cf.E_MAIL LIKE '%_@_%._%'                THEN LTRIM(RTRIM(cf.E_MAIL))
            END                                                          AS EMAIL_GREZZA,
            CASE WHEN i.E_MAIL IS NOT NULL                     THEN 'INTERLOCUTORE'
                 WHEN v.E_MAIL  LIKE '%_@_%._%'                THEN 'TESTATA_VETTORE'
                 WHEN cf.E_MAIL LIKE '%_@_%._%'                THEN 'ANAGRAFICA_FORNITORE'
            END                                                          AS POC_FONTE,
            COALESCE(NULLIF(i.NOMINATIVO, ''), NULLIF(LTRIM(RTRIM(v.INTERLOCUTORE)), '')) AS POC_NOMINATIVO_SGA,
            COALESCE(i.TELEFONO, NULLIF(LTRIM(RTRIM(v.CELLULARE)), ''),
                     NULLIF(LTRIM(RTRIM(v.TELEFONO)), ''), NULLIF(LTRIM(RTRIM(cf.TELEFONO)), '')) AS POC_TELEFONO,
            vp.N_VIAGGI,
            vp.ULTIMO_VIAGGIO,
            vp.N_REPARTI_FMI
    FROM    ViaggiPeriodo vp
    JOIN    dbo.T2BaseVettori v
              ON  v.SOCIETA = vp.SOCIETA AND v.CODICE = vp.VETTORE
    LEFT JOIN dbo.BaCliFor cf
              ON  cf.SOCIETA = v.SOCIETA
              AND cf.CLIENTE_FORNITORE = v.FORNITORE_CLIFOR
              AND cf.CODICE = v.FORNITORE_CODICE
    /* POC: primo interlocutore con e-mail valida, preferendo il tipo @TipoPOC.
       OUTER APPLY + TOP 1 (seek sulla PK) invece di ROW_NUMBER sull'intera tabella:
       la versione con ROW_NUMBER andava in timeout (> 80 s) il 11/11/2026 */
    OUTER APPLY (
        SELECT TOP 1
               LTRIM(RTRIM(x.NOMINATIVO)) AS NOMINATIVO,
               LTRIM(RTRIM(x.E_MAIL))     AS E_MAIL,
               COALESCE(NULLIF(LTRIM(RTRIM(x.CELLULARE)), ''), NULLIF(LTRIM(RTRIM(x.TELEFONO)), '')) AS TELEFONO
        FROM   dbo.T2BaseVettoriInterlocutori x
        WHERE  x.SOCIETA = v.SOCIETA AND x.CODICE = v.CODICE
          AND  x.E_MAIL LIKE '%_@_%._%'
        ORDER BY CASE WHEN x.TIPO = @TipoPOC THEN 0 ELSE 1 END, x.NUMERO_RIGA
    ) i
    WHERE   v.ATTIVO = 'S'
      AND   NULLIF(LTRIM(RTRIM(cf.PARTITA_IVA)), '') IS NOT NULL  -- scarta i vettori senza P.IVA (decisione 11/11/2026)
      AND   ISNULL(cf.BLOCCATO, 'N')   <> 'S'
      AND   ISNULL(cf.BLACK_LIST, 'N') <> 'S'
      AND   ISNULL(cf.PARTITA_IVA, '') <> @PivaFercam      -- esclude FERCAM (mezzi propri / infragruppo)
      -- esclude le società del gruppo censite in SGA (decisione 11/11/2026: si lavora solo su società 1)
      AND   NOT EXISTS (SELECT 1 FROM dbo.BaSocieta s
                        WHERE s.PARTITA_IVA IS NOT NULL AND s.PARTITA_IVA <> ''
                          AND s.PARTITA_IVA = cf.PARTITA_IVA)
      -- [DA VALUTARE] escludere anche AGENZIA = 'S', CONSORZIATO = 'S',
      --                 vettori in T2CoInParametriVettoriGestitiComePropri
)
/* 4. Output con il tracciato atteso dall'orchestratore */
SELECT  b.SOCIETA,
        b.CODICE_VETTORE,
        b.RAGIONE_SOCIALE,
        b.NAZIONE,
        b.PARTITA_IVA,
        -- Identificativo per P44 (type = VAT): prefisso paese se la P.IVA è solo numerica
        CASE WHEN b.PARTITA_IVA IS NULL OR b.PARTITA_IVA = '' THEN NULL
             WHEN b.PARTITA_IVA LIKE '[A-Z][A-Z]%'           THEN b.PARTITA_IVA
             WHEN b.NAZIONE = 'GR'                            THEN 'EL' + b.PARTITA_IVA  -- prefisso IVA Grecia
             ELSE b.NAZIONE + b.PARTITA_IVA
        END                                                   AS VAT_P44,
        b.CODICE_FISCALE,
        -- primo indirizzo se il campo ne contiene più di uno (separatori ; o ,)
        LOWER(CASE WHEN CHARINDEX(';', REPLACE(b.EMAIL_GREZZA, ',', ';')) > 0
                   THEN LTRIM(RTRIM(LEFT(REPLACE(b.EMAIL_GREZZA, ',', ';'),
                                         CHARINDEX(';', REPLACE(b.EMAIL_GREZZA, ',', ';')) - 1)))
                   ELSE b.EMAIL_GREZZA END)                   AS POC_EMAIL,
        COALESCE(b.POC_NOMINATIVO_SGA, @NominativoDefault)    AS POC_NOMINATIVO,
        CASE WHEN b.POC_NOMINATIVO_SGA IS NULL THEN 'S' ELSE 'N' END AS POC_NOMINATIVO_DEFAULT,
        -- givenName / familyName: split sul primo spazio (SGA ha un solo campo);
        -- con il nominativo di default givenName = 'Ufficio Traffico', familyName vuoto
        CASE WHEN b.POC_NOMINATIVO_SGA IS NULL                THEN @NominativoDefault
             WHEN CHARINDEX(' ', b.POC_NOMINATIVO_SGA) > 0
             THEN LEFT(b.POC_NOMINATIVO_SGA, CHARINDEX(' ', b.POC_NOMINATIVO_SGA) - 1)
             ELSE b.POC_NOMINATIVO_SGA END                    AS POC_NOME,
        CASE WHEN CHARINDEX(' ', b.POC_NOMINATIVO_SGA) > 0
             THEN LTRIM(SUBSTRING(b.POC_NOMINATIVO_SGA, CHARINDEX(' ', b.POC_NOMINATIVO_SGA) + 1, 100))
        END                                                   AS POC_COGNOME,
        b.POC_TELEFONO,
        CASE b.NAZIONE                                        -- locale ammessi da P44
             WHEN 'IT' THEN 'it-IT' WHEN 'DE' THEN 'de-DE' WHEN 'AT' THEN 'de-DE'
             WHEN 'FR' THEN 'fr-FR' WHEN 'ES' THEN 'es-ES' WHEN 'PL' THEN 'pl-PL'
             WHEN 'CZ' THEN 'cs-CZ' WHEN 'HU' THEN 'hu-HU' WHEN 'RO' THEN 'ro-RO'
             WHEN 'BG' THEN 'bg-BG' WHEN 'LT' THEN 'lt-LT' WHEN 'TR' THEN 'tr-TR'
             WHEN 'UA' THEN 'uk-UA' WHEN 'PT' THEN 'pt-BR'
             ELSE 'en-US'
        END                                                   AS POC_LOCALE,
        b.POC_FONTE,
        b.N_VIAGGI,
        b.ULTIMO_VIAGGIO,
        b.N_REPARTI_FMI,
        -- esito controllo qualità: l'orchestratore invita solo le righe OK
        CASE WHEN b.EMAIL_GREZZA IS NULL                      THEN 'KO_MANCA_EMAIL'
             ELSE 'OK'
        END                                                   AS ESITO_CONTROLLO
FROM    Base b
ORDER BY b.N_VIAGGI DESC, b.RAGIONE_SOCIALE;

/* Indici utili (verificare quelli esistenti):
   T2ViaggiVettori (SOCIETA, DATA) INCLUDE (VETTORE, REPARTO)  - filtro periodo + reparti
   PK T2BaseVettori / T2BaseVettoriInterlocutori / BaCliFor già coprono i join */
