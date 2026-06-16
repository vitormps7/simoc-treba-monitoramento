from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from typing import Any, Iterable

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except Exception:
    BeautifulSoup = None
    BS4_OK = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

# ============================================================
# CONFIGURACAO GERAL
# ============================================================

st.set_page_config(page_title="SIMOC-BA", page_icon="🛡️", layout="wide")

FUSO_HORARIO_BRASILIA = timezone(timedelta(hours=-3), name="BRT")
DOMINIO_INSTITUCIONAL = "@tre-ba.jus.br"
NOME_SISTEMA = "SIMOC-BA"
NOME_COMPLETO = "Sistema de Monitoramento Cartorário das Zonas Eleitorais"
UNIDADE_CORREGEDORIA = "Corregedoria Regional Eleitoral da Bahia"

PERFIS_CORREGEDORIA = {"admin", "corregedoria_gestor", "corregedoria_analista"}
PERFIS_ZONA = {"chefe_cartorio", "substituto"}
PERIODICIDADES = ["diariamente", "semanalmente", "quinzenalmente", "mensalmente", "bimestralmente", "trimestralmente", "anualmente", "por demanda"]
GRUPOS_PADRAO = ["ELO", "SISTEMAS DA INTRANET", "OBSERVAÇÕES", "OUTROS"]
STATUS_CHECKLIST = ["pendente", "em_analise", "validado", "devolvido", "nao_realizado"]

# Lista base: garante 001 a 205.
# O e-mail institucional da zona segue o padrão zona001@tre-ba.jus.br, zona002@tre-ba.jus.br etc.
# O município-sede é tratado como dado cadastral LOCAL, salvo no Supabase.
# Assim o sistema não consulta a internet a cada carregamento.
def email_padrao_zona(numero: int) -> str:
    return f"zona{int(numero):03d}@tre-ba.jus.br"


# Tabela fixa local de município-sede por Zona.
# Tabela preenchida a partir da lista fornecida pelo usuário (ZONA ELEITORAL / município-sede).
# A tela Zonas Eleitorais também permite importar CSV/XLSX e editar manualmente, gravando no Supabase.
MUNICIPIOS_SEDE_FIXOS: dict[int, str] = {
    1: "SALVADOR",
    2: "SALVADOR",
    3: "SALVADOR",
    4: "SALVADOR",
    5: "SALVADOR",
    6: "SALVADOR",
    7: "SALVADOR",
    8: "SALVADOR",
    9: "SALVADOR",
    10: "SALVADOR",
    11: "SALVADOR",
    12: "SALVADOR",
    13: "SALVADOR",
    14: "SALVADOR",
    15: "SALVADOR",
    16: "SALVADOR",
    17: "SALVADOR",
    18: "SALVADOR",
    19: "SALVADOR",
    20: "Zona eleitoral extinta",
    21: "ESPLANADA",
    22: "JEQUIÉ",
    23: "JEQUIÉ",
    24: "IPIAÚ",
    25: "ILHÉUS",
    26: "ILHÉUS",
    27: "ITABUNA",
    28: "ITABUNA",
    29: "IBICARAÍ",
    30: "NAZARÉ",
    31: "VALENÇA",
    32: "ITUBERÁ",
    33: "SIMÕES FILHO",
    34: "BELMONTE",
    35: "MUCURI",
    36: "AMARGOSA",
    37: "MARACÁS",
    38: "UBAÍRA",
    39: "VITÓRIA DA CONQUISTA",
    40: "VITÓRIA DA CONQUISTA",
    41: "VITÓRIA DA CONQUISTA",
    42: "ITABERABA",
    43: "CASTRO ALVES",
    44: "INHAMBUPE",
    45: "SENHOR DO BONFIM",
    46: "JACOBINA",
    47: "JUAZEIRO",
    48: "JUAZEIRO",
    49: "RIO REAL",
    50: "MONTE SANTO",
    51: "JEREMOABO",
    52: "PARIPIRANGA",
    53: "CAMPO FORMOSO",
    54: "MUNDO NOVO",
    55: "MORRO DO CHAPÉU",
    56: "SANTO ANTÔNIO DE JESUS",
    57: "MARAGOGIPE",
    58: "ITUAÇU",
    59: "POÇÕES",
    60: "CONDEÚBA",
    61: "CORIBE",
    62: "IPIRÁ",
    63: "CAETITÉ",
    64: "GUANAMBI",
    65: "MACAÚBAS",
    66: "CASA NOVA",
    67: "REMANSO",
    68: "XIQUE-XIQUE",
    69: "UTINGA",
    70: "BARREIRAS",
    71: "BOM JESUS DA LAPA",
    72: "SANTA MARIA DA VITÓRIA",
    73: "UBAITABA",
    74: "IRARÁ",
    75: "BARREIRAS",
    76: "JAGUAQUARA",
    77: "BARRA",
    78: "CAMAMU",
    79: "NOVA SOURE",
    80: "TUCANO",
    81: "OLINDINA",
    82: "CÍCERO DANTAS",
    83: "UAUÁ",
    84: "PAULO AFONSO",
    85: "CURAÇÁ",
    86: "MAIRI",
    87: "RUY BARBOSA",
    88: "SEABRA",
    89: "LENÇÓIS",
    90: "BRUMADO",
    91: "MACARANI",
    92: "JACARACI",
    93: "CACULÉ",
    94: "OLIVEIRA DOS BREJINHOS",
    95: "IRECÊ",
    96: "SENTO SÉ",
    97: "SANTA RITA DE CÁSSIA",
    98: "COTEGIPE",
    99: "SANTANA",
    100: "SÃO DESIDÉRIO",
    101: "LIVRAMENTO DE NOSSA SENHORA",
    102: "EUCLIDES DA CUNHA",
    103: "MIGUEL CALMON",
    104: "LAPÃO",
    105: "PIATÃ",
    106: "QUEIMADAS",
    107: "SANTA TERESINHA",
    108: "SÃO GONÇALO DOS CAMPOS",
    109: "MUTUÍPE",
    110: "RIBEIRA DO POMBAL",
    111: "PARAMIRIM",
    112: "PRADO",
    113: "RIACHO DE SANTANA",
    114: "RIACHÃO DO JACUÍPE",
    115: "SAÚDE",
    116: "CANAVIEIRAS",
    117: "URANDI",
    118: "CACHOEIRA",
    119: "ANDARAÍ",
    120: "VALENTE",
    121: "PORTO SEGURO",
    122: "PORTO SEGURO",
    123: "ARACI",
    124: "CORRENTINA",
    125: "CARINHANHA",
    126: "BAIANÓPOLIS",
    127: "CANDEIAS",
    128: "SÃO SEBASTIÃO DO PASSÉ",
    129: "CATU",
    130: "CORAÇÃO DE MARIA",
    131: "MURITIBA",
    132: "CONCEIÇÃO DO COITÉ",
    133: "CAMACAN",
    134: "UBATÃ",
    135: "COARACI",
    136: "ITAJUÍPE",
    137: "ITORORÓ",
    138: "ITARANTIM",
    139: "BARRA DO CHOÇA",
    140: "ITAPETINGA",
    141: "ITAPARICA",
    142: "CRUZ DAS ALMAS",
    143: "SANTO ESTEVÃO",
    144: "ENTRE RIOS",
    145: "SANTALUZ",
    146: "IGUAÍ",
    147: "ITAGIBÁ",
    148: "ITANHÉM",
    149: "ITIÚBA",
    150: "SERRINHA",
    151: "GANDU",
    152: "ENCRUZILHADA",
    153: "MEDEIROS NETO",
    154: "FEIRA DE SANTANA",
    155: "FEIRA DE SANTANA",
    156: "FEIRA DE SANTANA",
    157: "FEIRA DE SANTANA",
    158: "CHORROCHÓ",
    159: "CENTRAL",
    160: "SANTA BÁRBARA",
    161: "ANAGÉ",
    162: "SÃO FRANCISCO DO CONDE",
    163: "ALAGOINHAS",
    164: "ALAGOINHAS",
    165: "CÂNDIDO SALES",
    166: "BUERAREMA",
    167: "JACOBINA",
    168: "IGAPORÃ",
    169: "BARRA DA ESTIVA",
    170: "CAMAÇARI",
    171: "CAMAÇARI",
    172: "ITAMARAJU",
    173: "IBOTIRAMA",
    174: "CANARANA",
    175: "PALMAS DE MONTE ALTO",
    176: "BARRA DO MENDES",
    177: "TREMEDAL",
    178: "SANTO AMARO",
    179: "JAGUARARI",
    180: "LAURO DE FREITAS",
    181: "PAULO AFONSO",
    182: "RIACHÃO DAS NEVES",
    183: "TEIXEIRA DE FREITAS",
    184: "SÃO FELIPE",
    185: "MATA DE SÃO JOÃO",
    186: "DIAS D'ÁVILA",
    187: "FORMOSA DO RIO PRETO",
    188: "EUNÁPOLIS",
    189: "ITABELA",
    190: "SERRA DOURADA",
    191: "CAPIM GROSSO",
    192: "CONCEIÇÃO DO JACUÍPE",
    193: "IAÇU",
    194: "SERRA PRETA",
    195: "PILÃO ARCADO",
    196: "RETIROLÂNDIA",
    197: "WENCESLAU GUIMARÃES",
    198: "URUÇUCA",
    199: "JOÃO DOURADO",
    200: "POJUCA",
    201: "ITAMBÉ",
    202: "SANTO ANTÔNIO DE JESUS",
    203: "EUNÁPOLIS",
    204: "LAURO DE FREITAS",
    205: "LUÍS EDUARDO MAGALHÃES",
}


def sede_padrao_zona(numero: int) -> str:
    return MUNICIPIOS_SEDE_FIXOS.get(int(numero), "Município-sede pendente de cadastro")


ZONAS_PADRAO = [(i, f"{i:03d}ª Zona Eleitoral", sede_padrao_zona(i), email_padrao_zona(i)) for i in range(1, 206)]

# ============================================================
# ESTILO
# ============================================================

st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] {display: none !important;}
    div[data-testid="collapsedControl"] {display: none !important;}
    .block-container {padding-top: 1.2rem; max-width: 1480px;}
    .main-header {background: linear-gradient(90deg, #123E66 0%, #5FA6D9 100%); padding: 26px 30px; border-radius: 18px; color: #fff; margin-bottom: 22px; box-shadow: 0 12px 28px rgba(18,62,102,.16);} 
    .main-header h1 {font-size: 34px; margin:0 0 8px 0; font-weight: 900; letter-spacing: .5px;}
    .main-header p {margin: 3px 0; font-weight: 700;}
    .user-strip {background:#EEF6FF; border:1px solid #C8DAEF; color:#123E66; padding: 10px 14px; border-radius: 12px; margin-bottom: 16px; font-weight: 800;}
    .nav-box {background:#F7FAFE; border:1px solid #D8E3F0; padding:12px; border-radius:16px; margin-bottom:18px;}
    .module-card {background:#FFFFFF; border:0; border-radius:14px; padding:0; min-height:122px;} 
    .module-card h3 {margin:0 0 14px 0; color:#063B68; font-size:20px; font-weight:900;}
    .module-card p {margin:0 0 18px 0; color:#23384F; font-size:14px; line-height:1.45;}
    div[data-testid="stVerticalBlockBorderWrapper"] {border-color:#CAD9EA !important; border-radius:14px !important; box-shadow:0 7px 16px rgba(15,47,82,.05);}
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {height:100%;}
    .flow-box {background:#0F3F67; color:white; border-radius:16px; padding:18px 22px; margin:12px 0 20px 0;}
    .flow-box b {color:white;}
    .metric-card {background:#fff; border:1px solid #D7E0EA; border-radius:14px; padding:16px; box-shadow:0 4px 12px rgba(15,47,82,.05);} 
    .metric-card .label {font-size:12px; color:#65758A; text-transform:uppercase; font-weight:900;}
    .metric-card .value {font-size:28px; color:#123E66; font-weight:900; margin-top:3px;}
    .alert-danger {background:#FEF2F2; color:#991B1B; border:1px solid #FCA5A5; padding:12px 14px; border-radius:12px; margin:10px 0; font-weight:800;}
    .alert-warn {background:#FFFBEB; color:#92400E; border:1px solid #FCD34D; padding:12px 14px; border-radius:12px; margin:10px 0; font-weight:800;}
    .alert-ok {background:#F0FDF4; color:#166534; border:1px solid #86EFAC; padding:12px 14px; border-radius:12px; margin:10px 0; font-weight:800;}
    div.stButton > button {width:100%; border-radius:10px; border:1px solid #0F4C81; color:#0F3F67; background:white; font-weight:800; min-height:42px;}
    div.stButton > button:hover {border-color:#0F4C81; background:#EAF3FF; color:#0F3F67;}
    div[data-testid="stForm"] {border:1px solid #D7E0EA; border-radius:14px; padding:18px; background:#FFFFFF;}
    .small-muted {color:#65758A; font-size:13px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# UTILITARIOS
# ============================================================

def agora_brasilia() -> datetime:
    return datetime.now(FUSO_HORARIO_BRASILIA)


def hoje_brasilia() -> date:
    return agora_brasilia().date()


def fmt_data(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return v
    if isinstance(v, datetime):
        return v.astimezone(FUSO_HORARIO_BRASILIA).strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return str(v)


def normalizar_email(email: str | None) -> str:
    return (email or "").strip().lower()


def email_institucional(email: str) -> bool:
    email = normalizar_email(email)
    return email.endswith(DOMINIO_INSTITUCIONAL) or email == normalizar_email(get_secret("ADMIN_EMAIL", ""))


def get_secret(nome: str, padrao: str = "") -> str:
    try:
        return str(st.secrets.get(nome, os.getenv(nome, padrao)))
    except Exception:
        return os.getenv(nome, padrao)


def app_base_url() -> str:
    return get_secret("APP_BASE_URL", "").rstrip("/")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt.encode("ascii"), 220000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(dk).decode('ascii')}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        if stored.startswith("pbkdf2_sha256$"):
            _, salt, digest = stored.split("$", 2)
            dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt.encode("ascii"), 220000)
            return hmac.compare_digest(base64.b64encode(dk).decode("ascii"), digest)
        # compatibilidade com hashes antigos do passlib, quando disponivel
        try:
            from passlib.context import CryptContext
            ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
            return bool(ctx.verify(password or "", stored))
        except Exception:
            return False
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    url = get_secret("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não configurada nos Secrets do Streamlit.")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=1, pool_recycle=180, connect_args={"connect_timeout": 8})


def execute(sql: str, params: dict | None = None):
    engine = get_engine()
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def rows(sql: str, params: dict | None = None) -> list[dict]:
    engine = get_engine()
    with engine.begin() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings().all()]


def scalar(sql: str, params: dict | None = None) -> Any:
    engine = get_engine()
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def dataframe(sql: str, params: dict | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows(sql, params))



# ============================================================
# ZONAS ELEITORAIS DA BAHIA
# ============================================================

PLACEHOLDERS_SEDE = {
    "", None,
    "Município-sede não informado",
    "Município-sede pendente de atualização",
    "Sede não informada",
}


def _baixar_html(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SIMOC-BA"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def _limpar_texto(valor: object) -> str:
    txt = re.sub(r"\s+", " ", str(valor or "")).strip()
    return txt.strip(" -–—|;,")


def _extrair_numero_zona(valor: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\b", str(valor or ""))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 205 else None


def _indice_coluna(cabecalhos: list[str], termos: list[str]) -> int | None:
    cab = [c.upper() for c in cabecalhos]
    for i, c in enumerate(cab):
        if all(t.upper() in c for t in termos):
            return i
    return None


def extrair_zonas_tre_ba_html(html: str) -> dict[int, dict[str, str]]:
    """Extrai zona -> município-sede/e-mail de páginas públicas do TRE-BA.

    A página oficial pode mudar de layout. Por isso o parser aceita tabelas com cabeçalhos
    ou linhas simples contendo número da zona, município-sede e e-mail.
    """
    dados: dict[int, dict[str, str]] = {}
    if not html:
        return dados

    if BS4_OK and BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            trs = table.find_all("tr")
            if not trs:
                continue
            header_cells = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
            idx_zona = _indice_coluna(header_cells, ["ZONA"])
            idx_sede = _indice_coluna(header_cells, ["MUNIC", "SEDE"]) or _indice_coluna(header_cells, ["MUNICÍPIO", "SEDE"])
            idx_email = _indice_coluna(header_cells, ["E-MAIL"]) or _indice_coluna(header_cells, ["EMAIL"])

            for tr in trs[1:]:
                cells = [_limpar_texto(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                if len(cells) < 2:
                    continue
                zona_txt = cells[idx_zona] if idx_zona is not None and idx_zona < len(cells) else cells[0]
                n = _extrair_numero_zona(zona_txt)
                if not n:
                    continue
                sede = ""
                if idx_sede is not None and idx_sede < len(cells):
                    sede = cells[idx_sede]
                elif len(cells) > 1:
                    sede = cells[1]
                email = ""
                if idx_email is not None and idx_email < len(cells):
                    email = cells[idx_email]
                for cell in cells:
                    if "@" in cell and "tre-ba" in cell.lower():
                        email = cell
                        break
                if sede and sede.upper() not in {"MUNICÍPIO SEDE", "MUNICIPIO SEDE", "SEDE"}:
                    dados[n] = {"municipio_sede": sede, "email": normalizar_email(email) or email_padrao_zona(n)}

    # Fallback por linhas de texto: funciona se a página vier sem <table>, mas com texto estruturado.
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"\s+", " ", texto)
    padrao = re.compile(
        r"\b(\d{1,3})\s*(?:ª|a|º|o)?\s*(?:Zona|ZE)?\b\s*[-–—]?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç' .-]{2,60})",
        re.IGNORECASE,
    )
    for n_txt, sede in padrao.findall(texto):
        n = int(n_txt)
        if 1 <= n <= 205 and n not in dados:
            sede = _limpar_texto(sede)
            # Evita capturar palavras genéricas como cabeçalhos.
            if sede.upper() not in {"ZONA", "MUNICÍPIO", "MUNICIPIO", "ENDEREÇO", "ENDERECO", "E MAIL"}:
                dados[n] = {"municipio_sede": sede, "email": email_padrao_zona(n)}
    return dados


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def consultar_zonas_tre_ba_online() -> dict[int, dict[str, str]]:
    """Consulta a fonte pública do TRE-BA para preencher município-sede.

    Se a rede do Streamlit Cloud, do TRE-BA ou o layout da página impedir a leitura,
    retorna dicionário vazio e o sistema preserva o que já estiver no banco.
    """
    acumulado: dict[int, dict[str, str]] = {}
    for url in TRE_BA_ZONAS_URLS:
        try:
            html = _baixar_html(url)
            dados = extrair_zonas_tre_ba_html(html)
            for numero, info in dados.items():
                if numero not in acumulado or info.get("municipio_sede"):
                    acumulado[numero] = info
        except Exception:
            continue
    return acumulado


def aplicar_zonas_padrao(conn, usar_tabela_local: bool = True, sobrescrever_municipio: bool = False) -> tuple[int, int]:
    """Garante 001-205, e-mail padrão e município-sede vindo da tabela local.

    Não consulta internet no carregamento do sistema. A Corregedoria pode editar
    a sede manualmente ou importar uma tabela CSV/XLSX na tela Zonas Eleitorais.
    Retorna (zonas_garantidas, municipios_aplicados_da_tabela_local).
    """
    municipios_aplicados = 0
    for numero, nome, sede_base, email_base in ZONAS_PADRAO:
        sede_tabela = _limpar_texto(MUNICIPIOS_SEDE_FIXOS.get(int(numero), "")) if usar_tabela_local else ""
        sede = sede_tabela or _limpar_texto(sede_base)
        email = normalizar_email(email_base or email_padrao_zona(numero))
        conn.execute(text("""
            insert into simoc_zonas (numero, nome, municipio_sede, email)
            values (:numero, :nome, :sede, :email)
            on conflict (numero) do update set
                nome = excluded.nome,
                email = excluded.email,
                municipio_sede = case
                    when :sobrescrever = true then excluded.municipio_sede
                    when simoc_zonas.municipio_sede is null
                      or trim(simoc_zonas.municipio_sede) = ''
                      or simoc_zonas.municipio_sede in ('Município-sede não informado', 'Município-sede pendente de atualização', 'Município-sede pendente de cadastro', 'Sede não informada')
                    then excluded.municipio_sede
                    else simoc_zonas.municipio_sede
                end
        """), {"numero": numero, "nome": nome, "sede": sede, "email": email, "sobrescrever": sobrescrever_municipio})
        if sede_tabela:
            municipios_aplicados += 1
    return len(ZONAS_PADRAO), municipios_aplicados


def importar_tabela_zonas_csv(conn, df: pd.DataFrame, sobrescrever: bool = False) -> int:
    """Importa CSV/XLSX com colunas: numero, municipio_sede e opcionalmente email."""
    cols = {str(c).strip().lower(): c for c in df.columns}
    col_num = cols.get("numero") or cols.get("zona") or cols.get("número")
    col_sede = cols.get("municipio_sede") or cols.get("município_sede") or cols.get("municipio") or cols.get("município") or cols.get("sede")
    col_email = cols.get("email") or cols.get("e-mail")
    if not col_num or not col_sede:
        raise ValueError("A tabela precisa ter as colunas numero e municipio_sede.")
    atualizados = 0
    for _, r in df.iterrows():
        try:
            numero = int(str(r[col_num]).strip().replace("ª", "").split()[0])
        except Exception:
            continue
        if numero < 1 or numero > 205:
            continue
        sede = _limpar_texto(r[col_sede])
        if not sede:
            continue
        email = normalizar_email(r[col_email]) if col_email else email_padrao_zona(numero)
        if not email:
            email = email_padrao_zona(numero)
        conn.execute(text("""
            insert into simoc_zonas (numero, nome, municipio_sede, email)
            values (:numero, :nome, :sede, :email)
            on conflict (numero) do update set
                nome = excluded.nome,
                email = excluded.email,
                municipio_sede = case
                    when :sobrescrever = true then excluded.municipio_sede
                    when simoc_zonas.municipio_sede is null
                      or trim(simoc_zonas.municipio_sede) = ''
                      or simoc_zonas.municipio_sede in ('Município-sede não informado', 'Município-sede pendente de atualização', 'Município-sede pendente de cadastro', 'Sede não informada')
                    then excluded.municipio_sede
                    else simoc_zonas.municipio_sede
                end
        """), {"numero": numero, "nome": f"{numero:03d}ª Zona Eleitoral", "sede": sede, "email": email, "sobrescrever": sobrescrever})
        atualizados += 1
    return atualizados


def modelo_csv_zonas() -> bytes:
    df = pd.DataFrame([
        {"numero": i, "zona": f"{i:03d}ª Zona Eleitoral", "municipio_sede": MUNICIPIOS_SEDE_FIXOS.get(i, ""), "email": email_padrao_zona(i)}
        for i in range(1, 206)
    ])
    return df.to_csv(index=False, sep=";").encode("utf-8-sig")

def contar_zonas_sem_municipio(conn) -> int:
    return conn.execute(text("""
        select count(*)
        from simoc_zonas
        where municipio_sede is null
           or trim(municipio_sede) = ''
           or municipio_sede in ('Município-sede não informado', 'Município-sede pendente de atualização', 'Sede não informada')
    """)).scalar() or 0


def registrar_municipios_sede_no_sistema(conn) -> tuple[int, int]:
    """Registra e-mail padrão e município-sede pela tabela local fixa.

    Esta função não consulta a internet; mantém compatibilidade com versões
    anteriores e aplica apenas a tabela local/editável.
    """
    return aplicar_zonas_padrao(conn, usar_tabela_local=True, sobrescrever_municipio=False)


# ============================================================
# BANCO / SCHEMA
# ============================================================

@st.cache_resource(show_spinner=False)
def bootstrap_schema_once() -> bool:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
        create table if not exists simoc_zonas (
            id serial primary key,
            numero integer unique not null,
            nome text not null,
            municipio_sede text,
            email text,
            ativa boolean default true,
            criado_em timestamptz default now()
        );
        """))
        conn.execute(text("""
        create table if not exists simoc_usuarios (
            id serial primary key,
            nome text not null,
            email text unique not null,
            senha_hash text not null,
            perfil text not null,
            zona_id integer references simoc_zonas(id),
            ativo boolean default true,
            validado boolean default false,
            token_validacao text,
            token_recuperacao text,
            token_recuperacao_expira_em timestamptz,
            ultimo_login timestamptz,
            criado_em timestamptz default now(),
            atualizado_em timestamptz default now()
        );
        """))
        conn.execute(text("""
        create table if not exists simoc_atividades (
            id serial primary key,
            grupo text not null default 'OUTROS',
            descricao text not null,
            periodicidade text not null,
            responsavel_referencia text,
            prazo_dias integer default 5,
            orientacao text,
            exige_evidencia boolean default false,
            ativa boolean default true,
            criado_por integer references simoc_usuarios(id),
            criado_em timestamptz default now(),
            atualizado_em timestamptz default now()
        );
        """))
        conn.execute(text("""
        create table if not exists simoc_checklists (
            id serial primary key,
            atividade_id integer not null references simoc_atividades(id),
            zona_id integer not null references simoc_zonas(id),
            periodo_inicio date not null,
            periodo_fim date not null,
            prazo_preenchimento date not null,
            status text not null default 'pendente',
            responsavel_zona text,
            realizado boolean default false,
            data_execucao date,
            observacao_zona text,
            evidencia_url text,
            enviado_em timestamptz,
            validado_em timestamptz,
            validado_por integer references simoc_usuarios(id),
            comentario_corregedoria text,
            criado_em timestamptz default now(),
            atualizado_em timestamptz default now(),
            unique (atividade_id, zona_id, periodo_inicio, periodo_fim)
        );
        """))
        conn.execute(text("""
        create table if not exists simoc_mensagens (
            id serial primary key,
            zona_id integer references simoc_zonas(id),
            titulo text not null,
            mensagem text not null,
            tipo text default 'manual',
            checklist_id integer references simoc_checklists(id),
            criada_por integer references simoc_usuarios(id),
            criada_em timestamptz default now(),
            lida_em timestamptz
        );
        """))
        conn.execute(text("""
        create table if not exists simoc_config (
            chave text primary key,
            valor text,
            atualizado_em timestamptz default now()
        );
        
        create table if not exists simoc_auditoria (
            id serial primary key,
            usuario_id integer,
            acao text not null,
            entidade text,
            entidade_id text,
            detalhe text,
            criado_em timestamptz default now()
        );
        """))
        # Garante colunas caso alguma tabela ja exista incompleta
        alteracoes = [
            "alter table simoc_checklists add column if not exists responsavel_zona text",
            "alter table simoc_checklists add column if not exists realizado boolean default false",
            "alter table simoc_checklists add column if not exists observacao_zona text",
            "alter table simoc_checklists add column if not exists evidencia_url text",
            "alter table simoc_checklists add column if not exists comentario_corregedoria text",
            "alter table simoc_atividades add column if not exists prazo_dias integer default 5",
            "alter table simoc_atividades add column if not exists responsavel_referencia text",
            "alter table simoc_atividades add column if not exists orientacao text",
            "alter table simoc_atividades add column if not exists exige_evidencia boolean default false",
        ]
        for sql in alteracoes:
            conn.execute(text(sql))
        # Zonas base: garante 001-205 e e-mail institucional padronizado.
        # Não consulta internet no carregamento; município-sede vem da tabela local/editável.
        registrar_municipios_sede_no_sistema(conn)
        # Admin inicial
        admin_email = normalizar_email(get_secret("ADMIN_EMAIL", ""))
        admin_password = get_secret("ADMIN_PASSWORD", "")
        if admin_email and admin_password:
            existe = conn.execute(text("select id from simoc_usuarios where email=:email"), {"email": admin_email}).scalar()
            if not existe:
                conn.execute(text("""
                    insert into simoc_usuarios (nome, email, senha_hash, perfil, ativo, validado)
                    values ('Administrador', :email, :senha, 'admin', true, true)
                """), {"email": admin_email, "senha": hash_password(admin_password)})
    return True


def registrar_auditoria(acao: str, entidade: str = "", entidade_id: Any = None, detalhe: str = ""):
    try:
        u = st.session_state.get("user") or {}
        execute("""
            insert into simoc_auditoria (usuario_id, acao, entidade, entidade_id, detalhe)
            values (:uid, :acao, :entidade, :entidade_id, :detalhe)
        """, {"uid": u.get("id"), "acao": acao, "entidade": entidade, "entidade_id": str(entidade_id or ""), "detalhe": detalhe})
    except Exception:
        pass


# ============================================================
# EMAIL / LINKS
# ============================================================

def enviar_email(destino: str, assunto: str, corpo: str) -> tuple[bool, str]:
    host = get_secret("SMTP_HOST")
    user = get_secret("SMTP_USER")
    password = get_secret("SMTP_PASSWORD")
    remetente = get_secret("EMAIL_REMETENTE", user)
    porta = int(get_secret("SMTP_PORT", "587") or "587")
    if not host or not user or not password or not remetente:
        return False, "SMTP não configurado."
    try:
        msg = EmailMessage()
        msg["Subject"] = assunto
        msg["From"] = remetente
        msg["To"] = destino
        msg.set_content(corpo)
        with smtplib.SMTP(host, porta, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True, "E-mail enviado."
    except Exception as e:
        return False, f"Falha ao enviar e-mail: {e}"


def link_validacao(token: str) -> str:
    base = app_base_url()
    return f"{base}?validar={token}" if base else f"?validar={token}"


def link_recuperacao(token: str) -> str:
    base = app_base_url()
    return f"{base}?recuperar={token}" if base else f"?recuperar={token}"


# ============================================================
# COMPONENTES VISUAIS
# ============================================================

def header():
    st.markdown(f"""
    <div class='main-header'>
        <h1>🛡️ {NOME_SISTEMA}</h1>
        <p>{NOME_COMPLETO}</p>
        <p>{UNIDADE_CORREGEDORIA} · Fiscalização, prazos, checklist e comunicação com as Zonas Eleitorais</p>
    </div>
    """, unsafe_allow_html=True)


def usuario_logado() -> dict | None:
    return st.session_state.get("user")


def eh_corregedoria() -> bool:
    u = usuario_logado() or {}
    return u.get("perfil") in PERFIS_CORREGEDORIA


def eh_zona() -> bool:
    u = usuario_logado() or {}
    return u.get("perfil") in PERFIS_ZONA


def user_strip():
    u = usuario_logado() or {}
    zona = ""
    if u.get("zona_numero"):
        zona = f" · Zona {int(u['zona_numero']):03d} - {u.get('municipio_sede') or ''}"
    st.markdown(f"<div class='user-strip'>Usuário: {u.get('nome')} · Perfil: {u.get('perfil')}{zona}</div>", unsafe_allow_html=True)


def set_page(key: str, page: str):
    st.session_state[key] = page


def nav(paginas: list[str], key: str) -> str:
    if key not in st.session_state or st.session_state[key] not in paginas:
        st.session_state[key] = paginas[0]
    widget_key = f"{key}_widget"
    idx = paginas.index(st.session_state[key])
    st.markdown("<div class='nav-box'>", unsafe_allow_html=True)
    pagina = st.radio("Navegação", paginas, horizontal=True, index=idx, key=widget_key, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
    st.session_state[key] = pagina
    return pagina


def card(titulo: str, texto: str):
    st.markdown(f"<div class='module-card'><h3>{titulo}</h3><p>{texto}</p></div>", unsafe_allow_html=True)


def action_card(titulo: str, texto: str, botao: str, destino: str, nav_key: str = "nav_cor", button_key: str | None = None):
    with st.container(border=True):
        card(titulo, texto)
        st.button(botao, key=button_key or f"btn_{nav_key}_{destino}", on_click=set_page, args=(nav_key, destino))


def metric_card(label: str, value: Any):
    st.markdown(f"<div class='metric-card'><div class='label'>{label}</div><div class='value'>{value}</div></div>", unsafe_allow_html=True)


def alert(tipo: str, msg: str):
    cls = {"ok": "alert-ok", "warn": "alert-warn", "danger": "alert-danger"}.get(tipo, "alert-warn")
    st.markdown(f"<div class='{cls}'>{msg}</div>", unsafe_allow_html=True)


def zona_options(incluir_todas=False) -> list[str]:
    zs = rows("select id, numero, municipio_sede from simoc_zonas where ativa=true order by numero")
    opts = [f"{z['id']} | {int(z['numero']):03d}ª ZE - {z.get('municipio_sede') or 'Sede não informada'}" for z in zs]
    return (["Todas as Zonas"] if incluir_todas else []) + opts


def zona_id_from_label(label: str | None) -> int | None:
    if not label or label == "Todas as Zonas":
        return None
    try:
        return int(str(label).split("|", 1)[0].strip())
    except Exception:
        return None


# ============================================================
# AUTENTICACAO
# ============================================================

def processar_links_publicos():
    params = st.query_params
    if "validar" in params:
        bootstrap_schema_once()
        token = params.get("validar")
        row = rows("select id, email from simoc_usuarios where token_validacao=:t", {"t": token})
        if row:
            execute("update simoc_usuarios set validado=true, token_validacao=null, atualizado_em=now() where id=:id", {"id": row[0]["id"]})
            st.success("Cadastro validado. Você já pode entrar no sistema.")
            registrar_auditoria("validacao_usuario", "simoc_usuarios", row[0]["id"], row[0]["email"])
        else:
            st.warning("Link de validação inválido ou já utilizado.")
        st.query_params.clear()

    if "recuperar" in params:
        bootstrap_schema_once()
        token = params.get("recuperar")
        row = rows("""
            select id, email from simoc_usuarios
            where token_recuperacao=:t and token_recuperacao_expira_em >= now()
        """, {"t": token})
        if not row:
            st.error("Link de recuperação inválido ou expirado.")
            return True
        st.subheader("Redefinir senha")
        with st.form("form_redefinir"):
            nova = st.text_input("Nova senha", type="password")
            conf = st.text_input("Confirmar nova senha", type="password")
            ok = st.form_submit_button("Salvar nova senha")
        if ok:
            if len(nova or "") < 6:
                st.warning("A senha deve ter pelo menos 6 caracteres.")
            elif nova != conf:
                st.warning("As senhas não conferem.")
            else:
                execute("""
                    update simoc_usuarios
                    set senha_hash=:h, token_recuperacao=null, token_recuperacao_expira_em=null, atualizado_em=now()
                    where id=:id
                """, {"h": hash_password(nova), "id": row[0]["id"]})
                registrar_auditoria("recuperacao_senha", "simoc_usuarios", row[0]["id"], row[0]["email"])
                st.success("Senha redefinida. Faça login novamente.")
                st.query_params.clear()
        return True
    return False


def tela_login():
    header()
    processar_links_publicos()
    abas = st.tabs(["Entrar", "Cadastrar usuário", "Recuperar senha"])
    with abas[0]:
        st.subheader("Acesso ao sistema")
        with st.form("login_form"):
            email = normalizar_email(st.text_input("E-mail"))
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", type="primary")
        if entrar:
            bootstrap_schema_once()
            row = rows("""
                select u.*, z.numero as zona_numero, z.municipio_sede
                from simoc_usuarios u
                left join simoc_zonas z on z.id=u.zona_id
                where u.email=:email and u.ativo=true
            """, {"email": email})
            if row and row[0].get("validado") and verify_password(senha, row[0].get("senha_hash")):
                execute("update simoc_usuarios set ultimo_login=now() where id=:id", {"id": row[0]["id"]})
                u = row[0]
                u.pop("senha_hash", None)
                st.session_state.user = u
                registrar_auditoria("login", "simoc_usuarios", u["id"], email)
                st.rerun()
            elif row and not row[0].get("validado"):
                st.warning("Cadastro ainda não validado pela Corregedoria ou pelo link de validação.")
            else:
                st.error("Usuário ou senha inválidos.")

    with abas[1]:
        st.subheader("Cadastrar usuário")
        st.caption("Usuários das Zonas devem escolher a Zona correspondente. A Corregedoria poderá validar o cadastro.")
        with st.form("cadastro_form"):
            nome = st.text_input("Nome completo")
            email = normalizar_email(st.text_input("E-mail institucional"))
            perfil = st.selectbox("Perfil", ["chefe_cartorio", "substituto", "corregedoria_analista"])
            zlabel = st.selectbox("Zona vinculada", zona_options() if get_secret("DATABASE_URL") else ["Configure o banco primeiro"], disabled=(perfil not in PERFIS_ZONA))
            senha = st.text_input("Senha", type="password")
            conf = st.text_input("Confirmar senha", type="password")
            cadastrar = st.form_submit_button("Cadastrar")
        if cadastrar:
            bootstrap_schema_once()
            if not nome.strip():
                st.warning("Informe o nome.")
            elif not email_institucional(email):
                st.warning(f"Use e-mail institucional {DOMINIO_INSTITUCIONAL}.")
            elif senha != conf or len(senha or "") < 6:
                st.warning("As senhas não conferem ou têm menos de 6 caracteres.")
            elif perfil in PERFIS_ZONA and not zona_id_from_label(zlabel):
                st.warning("Selecione a Zona vinculada.")
            elif scalar("select id from simoc_usuarios where email=:email", {"email": email}):
                st.warning("Este e-mail já está cadastrado.")
            else:
                token = secrets.token_urlsafe(32)
                zid = zona_id_from_label(zlabel) if perfil in PERFIS_ZONA else None
                rid = scalar("""
                    insert into simoc_usuarios (nome, email, senha_hash, perfil, zona_id, ativo, validado, token_validacao)
                    values (:nome, :email, :senha, :perfil, :zona_id, true, false, :token)
                    returning id
                """, {"nome": nome.strip(), "email": email, "senha": hash_password(senha), "perfil": perfil, "zona_id": zid, "token": token})
                link = link_validacao(token)
                ok, msg = enviar_email(email, f"Validação de cadastro - {NOME_SISTEMA}", f"Olá, {nome}.\n\nValide seu cadastro no SIMOC-BA:\n{link}")
                registrar_auditoria("cadastro_usuario", "simoc_usuarios", rid, email)
                if ok:
                    st.success("Cadastro realizado. Link de validação enviado ao e-mail.")
                else:
                    st.warning(f"Cadastro realizado. {msg} Link de validação: {link}")

    with abas[2]:
        st.subheader("Recuperar senha")
        email = normalizar_email(st.text_input("E-mail cadastrado", key="email_rec"))
        if st.button("Gerar link de recuperação"):
            bootstrap_schema_once()
            row = rows("select id, nome, email from simoc_usuarios where email=:email and ativo=true", {"email": email})
            if not row:
                st.error("E-mail não encontrado.")
            else:
                token = secrets.token_urlsafe(32)
                expira = agora_brasilia() + timedelta(hours=2)
                execute("""
                    update simoc_usuarios set token_recuperacao=:t, token_recuperacao_expira_em=:e, atualizado_em=now()
                    where id=:id
                """, {"t": token, "e": expira, "id": row[0]["id"]})
                link = link_recuperacao(token)
                ok, msg = enviar_email(email, f"Recuperação de senha - {NOME_SISTEMA}", f"Olá.\n\nUse o link para redefinir sua senha:\n{link}\n\nO link expira em 2 horas.")
                registrar_auditoria("gerar_recuperacao_senha", "simoc_usuarios", row[0]["id"], email)
                if ok:
                    st.success("Link enviado ao e-mail cadastrado.")
                else:
                    st.warning(f"{msg} Link de recuperação: {link}")


# ============================================================
# REGRAS DE NEGOCIO
# ============================================================

def gerar_checklists(atividade_id: int, zona_id: int | None, inicio: date, fim: date, prazo: date) -> int:
    if zona_id:
        zonas = rows("select id from simoc_zonas where id=:id and ativa=true", {"id": zona_id})
    else:
        zonas = rows("select id from simoc_zonas where ativa=true order by numero")
    count = 0
    for z in zonas:
        execute("""
            insert into simoc_checklists (atividade_id, zona_id, periodo_inicio, periodo_fim, prazo_preenchimento, status)
            values (:atividade, :zona, :inicio, :fim, :prazo, 'pendente')
            on conflict (atividade_id, zona_id, periodo_inicio, periodo_fim) do nothing
        """, {"atividade": atividade_id, "zona": z["id"], "inicio": inicio, "fim": fim, "prazo": prazo})
        count += 1
    registrar_auditoria("gerar_checklists", "simoc_atividades", atividade_id, f"{count} zonas")
    return count


def gerar_mensagens_atraso_automaticas() -> int:
    atrasadas = rows("""
        select c.id, c.zona_id, z.numero, a.descricao, c.prazo_preenchimento
        from simoc_checklists c
        join simoc_atividades a on a.id=c.atividade_id
        join simoc_zonas z on z.id=c.zona_id
        where c.status in ('pendente','devolvido') and c.prazo_preenchimento < :hoje
    """, {"hoje": hoje_brasilia()})
    criadas = 0
    for r in atrasadas:
        ja = scalar("""
            select id from simoc_mensagens
            where tipo='atraso_auto' and checklist_id=:cid and date(criada_em at time zone 'America/Sao_Paulo')=:hoje
        """, {"cid": r["id"], "hoje": hoje_brasilia()})
        if ja:
            continue
        execute("""
            insert into simoc_mensagens (zona_id, titulo, mensagem, tipo, checklist_id, criada_por)
            values (:zona, :titulo, :mensagem, 'atraso_auto', :cid, :uid)
        """, {
            "zona": r["zona_id"],
            "titulo": "Checklist em atraso",
            "mensagem": f"A atividade '{r['descricao']}' está pendente/devolvida após o prazo de {fmt_data(r['prazo_preenchimento'])}. Regularize o checklist ou registre observação justificando a pendência.",
            "cid": r["id"],
            "uid": (usuario_logado() or {}).get("id"),
        })
        criadas += 1
    if criadas:
        registrar_auditoria("mensagens_atraso_auto", "simoc_checklists", detalhe=str(criadas))
    return criadas


def df_checklists_filtrado(status="Todos", periodicidade="Todas", grupo="Todos", zona_id=None, inicio=None, fim=None):
    cond = ["1=1"]
    params = {}
    if status != "Todos":
        cond.append("c.status=:status")
        params["status"] = status
    if periodicidade != "Todas":
        cond.append("a.periodicidade=:periodicidade")
        params["periodicidade"] = periodicidade
    if grupo != "Todos":
        cond.append("a.grupo=:grupo")
        params["grupo"] = grupo
    if zona_id:
        cond.append("c.zona_id=:zona")
        params["zona"] = zona_id
    if inicio:
        cond.append("c.periodo_inicio>=:inicio")
        params["inicio"] = inicio
    if fim:
        cond.append("c.periodo_fim<=:fim")
        params["fim"] = fim
    sql = f"""
        select c.id, z.numero as zona, z.municipio_sede, a.grupo, a.descricao as atividade, a.periodicidade,
               c.periodo_inicio, c.periodo_fim, c.prazo_preenchimento, c.status, c.responsavel_zona,
               c.realizado, c.data_execucao, c.observacao_zona, c.evidencia_url, c.enviado_em,
               c.comentario_corregedoria
        from simoc_checklists c
        join simoc_atividades a on a.id=c.atividade_id
        join simoc_zonas z on z.id=c.zona_id
        where {' and '.join(cond)}
        order by c.prazo_preenchimento desc, z.numero, a.descricao
    """
    df = dataframe(sql, params)
    if not df.empty:
        for col in ["periodo_inicio", "periodo_fim", "prazo_preenchimento", "data_execucao", "enviado_em"]:
            if col in df.columns:
                df[col] = df[col].apply(fmt_data)
    return df


# ============================================================
# PAGINAS CORREGEDORIA
# ============================================================

def pagina_inicio_corregedoria():
    st.markdown("<div class='flow-box'><b>Fluxo correto:</b> a Corregedoria cadastra a atividade e a periodicidade → gera checklist para as Zonas → a Zona informa o responsável, observa e marca a realização → a Corregedoria acompanha, alerta e valida.</div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        action_card("📌 Atividades monitoradas", "Cadastrar a atividade, periodicidade, período de execução e prazo para resposta das Zonas.", "Abrir atividades", "Atividades", button_key="home_atividades")
    with col2:
        action_card("📊 Acompanhamento", "Controlar atividades pendentes, realizadas, em análise e atrasadas por Zona Eleitoral.", "Abrir acompanhamento", "Acompanhamento", button_key="home_acomp")
    with col3:
        action_card("✉️ Comunicação", "Enviar mensagens às Zonas, inclusive orientações e cobranças de atraso.", "Abrir mensagens", "Mensagens", button_key="home_msg")
    col4, col5, col6 = st.columns(3)
    with col4:
        action_card("✅ Validação", "Validar ou devolver os checklists enviados pelas Zonas.", "Validar checklists", "Validação", button_key="home_val")
    with col5:
        action_card("📄 Relatórios", "Filtrar por Zona, status, periodicidade, grupo e período. Exportar Excel ou PDF.", "Emitir relatórios", "Relatórios", button_key="home_rel")
    with col6:
        action_card("💾 Backup", "Gerar backup completo do sistema em JSON e restaurar apenas com confirmação expressa.", "Abrir backup", "Backup", button_key="home_backup")


def pagina_atividades():
    st.subheader("Atividades monitoradas e geração de checklist")
    st.caption("Cadastre a atividade, defina periodicidade e período. Ao salvar, o sistema gera o checklist para todas as Zonas ou para uma Zona específica.")
    with st.form("form_nova_atividade"):
        c1, c2 = st.columns([1, 2])
        with c1:
            grupo = st.selectbox("Grupo", GRUPOS_PADRAO)
            periodicidade = st.selectbox("Periodicidade", PERIODICIDADES)
            prazo_dias = st.number_input("Prazo padrão em dias", min_value=0, max_value=365, value=5)
            exige_evidencia = st.checkbox("Exigir link/evidência")
        with c2:
            descricao = st.text_area("Atividade a ser monitorada", placeholder="Ex.: RAE em diligência; Banco de Erros; PJe; Diário DJE...")
            responsavel_ref = st.text_input("Responsável de referência da planilha", placeholder="Ex.: Emerson e Rosy; Juanil e Marcelo")
            orientacao = st.text_area("Orientação da Corregedoria para a Zona")
        st.markdown("**Período de execução e prazo para resposta**")
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            inicio = st.date_input("Início da execução", value=hoje_brasilia(), format="DD/MM/YYYY")
        with d2:
            fim = st.date_input("Fim da execução", value=hoje_brasilia(), format="DD/MM/YYYY")
        with d3:
            prazo = st.date_input("Prazo para a Zona preencher", value=hoje_brasilia() + timedelta(days=5), format="DD/MM/YYYY")
        with d4:
            destino = st.selectbox("Destino", zona_options(incluir_todas=True))
        salvar = st.form_submit_button("Cadastrar atividade e gerar checklist", type="primary")
    if salvar:
        if not descricao.strip():
            st.warning("Informe a atividade a ser monitorada.")
        elif fim < inicio:
            st.warning("A data final não pode ser anterior à inicial.")
        else:
            uid = (usuario_logado() or {}).get("id")
            aid = scalar("""
                insert into simoc_atividades (grupo, descricao, periodicidade, responsavel_referencia, prazo_dias, orientacao, exige_evidencia, criado_por)
                values (:grupo, :descricao, :periodicidade, :resp, :prazo_dias, :orientacao, :exige, :uid)
                returning id
            """, {"grupo": grupo, "descricao": descricao.strip(), "periodicidade": periodicidade, "resp": responsavel_ref.strip(), "prazo_dias": int(prazo_dias), "orientacao": orientacao.strip(), "exige": exige_evidencia, "uid": uid})
            qtd = gerar_checklists(aid, zona_id_from_label(destino), inicio, fim, prazo)
            registrar_auditoria("cadastrar_atividade", "simoc_atividades", aid, descricao[:120])
            st.success(f"Atividade cadastrada e checklist gerado para {qtd} Zona(s).")

    st.markdown("---")
    st.subheader("Atividades cadastradas")
    df = dataframe("""
        select id, grupo, descricao, periodicidade, responsavel_referencia, prazo_dias, ativa, criado_em
        from simoc_atividades order by criado_em desc
    """)
    if not df.empty:
        df["criado_em"] = df["criado_em"].apply(fmt_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("Gerar novo período de checklist para atividade já cadastrada"):
        atividades = rows("select id, descricao, periodicidade from simoc_atividades where ativa=true order by descricao")
        if atividades:
            opts = [f"{a['id']} | {a['descricao']} ({a['periodicidade']})" for a in atividades]
            with st.form("form_periodo_existente"):
                escolha = st.selectbox("Atividade", opts)
                c1, c2, c3, c4 = st.columns(4)
                with c1: inicio2 = st.date_input("Início", value=hoje_brasilia(), key="inicio2", format="DD/MM/YYYY")
                with c2: fim2 = st.date_input("Fim", value=hoje_brasilia(), key="fim2", format="DD/MM/YYYY")
                with c3: prazo2 = st.date_input("Prazo", value=hoje_brasilia()+timedelta(days=5), key="prazo2", format="DD/MM/YYYY")
                with c4: destino2 = st.selectbox("Destino", zona_options(incluir_todas=True), key="destino2")
                ok = st.form_submit_button("Gerar checklist do período")
            if ok:
                aid = int(escolha.split("|",1)[0].strip())
                qtd = gerar_checklists(aid, zona_id_from_label(destino2), inicio2, fim2, prazo2)
                st.success(f"Checklist gerado para {qtd} Zona(s).")
        else:
            st.info("Nenhuma atividade cadastrada.")


def pagina_acompanhamento():
    criadas = gerar_mensagens_atraso_automaticas()
    if criadas:
        alert("warn", f"Foram geradas {criadas} mensagem(ns) automática(s) de atraso para as Zonas.")
    total = scalar("select count(*) from simoc_checklists") or 0
    pend = scalar("select count(*) from simoc_checklists where status='pendente'") or 0
    analise = scalar("select count(*) from simoc_checklists where status='em_analise'") or 0
    valid = scalar("select count(*) from simoc_checklists where status='validado'") or 0
    atras = scalar("select count(*) from simoc_checklists where status in ('pendente','devolvido') and prazo_preenchimento < :h", {"h": hoje_brasilia()}) or 0
    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: metric_card("Total", total)
    with c2: metric_card("Pendentes", pend)
    with c3: metric_card("Em análise", analise)
    with c4: metric_card("Validados", valid)
    with c5: metric_card("Atrasados", atras)
    if atras:
        alert("danger", f"Há {atras} checklist(s) em atraso. As Zonas recebem alerta automático e a Corregedoria pode enviar mensagem manual.")
    st.subheader("Controle de realização por Zona")
    df = df_checklists_filtrado()
    st.dataframe(df, use_container_width=True, hide_index=True)


def pagina_validacao():
    st.subheader("Validar checklists enviados pelas Zonas")
    itens = rows("""
        select c.id, z.numero, z.municipio_sede, a.descricao, a.periodicidade, c.periodo_inicio, c.periodo_fim,
               c.responsavel_zona, c.data_execucao, c.observacao_zona, c.evidencia_url, c.enviado_em, c.status
        from simoc_checklists c
        join simoc_atividades a on a.id=c.atividade_id
        join simoc_zonas z on z.id=c.zona_id
        where c.status='em_analise'
        order by c.enviado_em nulls last, z.numero
    """)
    if not itens:
        st.info("Nenhum checklist aguardando validação.")
        return
    for r in itens:
        with st.expander(f"Zona {int(r['numero']):03d} - {r['municipio_sede']} | {r['descricao']}"):
            st.write(f"**Periodicidade:** {r['periodicidade']} | **Período:** {fmt_data(r['periodo_inicio'])} a {fmt_data(r['periodo_fim'])}")
            st.write(f"**Responsável na Zona:** {r.get('responsavel_zona') or '-'}")
            st.write(f"**Data de execução:** {fmt_data(r.get('data_execucao'))}")
            st.write(f"**Observação da Zona:** {r.get('observacao_zona') or '-'}")
            if r.get("evidencia_url"):
                st.write(f"**Evidência/SEI:** {r['evidencia_url']}")
            comentario = st.text_area("Comentário da Corregedoria", key=f"coment_val_{r['id']}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Validar", key=f"validar_{r['id']}"):
                    execute("""
                        update simoc_checklists set status='validado', validado_em=now(), validado_por=:uid,
                        comentario_corregedoria=:c, atualizado_em=now() where id=:id
                    """, {"uid": usuario_logado()["id"], "c": comentario, "id": r["id"]})
                    registrar_auditoria("validar_checklist", "simoc_checklists", r["id"])
                    st.success("Checklist validado.")
                    st.rerun()
            with c2:
                if st.button("Devolver para ajuste", key=f"devolver_{r['id']}"):
                    execute("""
                        update simoc_checklists set status='devolvido', comentario_corregedoria=:c, atualizado_em=now() where id=:id
                    """, {"c": comentario or "Devolvido para ajuste pela Corregedoria.", "id": r["id"]})
                    execute("""
                        insert into simoc_mensagens (zona_id, titulo, mensagem, tipo, checklist_id, criada_por)
                        values ((select zona_id from simoc_checklists where id=:id), 'Checklist devolvido', :msg, 'devolucao', :id, :uid)
                    """, {"id": r["id"], "msg": comentario or "Checklist devolvido para ajuste.", "uid": usuario_logado()["id"]})
                    registrar_auditoria("devolver_checklist", "simoc_checklists", r["id"])
                    st.warning("Checklist devolvido e mensagem enviada à Zona.")
                    st.rerun()


def pagina_mensagens_corregedoria():
    st.subheader("Comunicação da Corregedoria com as Zonas")
    with st.form("form_msg"):
        destino = st.selectbox("Destino", zona_options(incluir_todas=True))
        titulo = st.text_input("Título")
        msg = st.text_area("Mensagem à Zona")
        enviar = st.form_submit_button("Enviar mensagem", type="primary")
    if enviar:
        if not titulo.strip() or not msg.strip():
            st.warning("Informe título e mensagem.")
        else:
            if destino == "Todas as Zonas":
                zonas = rows("select id from simoc_zonas where ativa=true")
            else:
                zonas = [{"id": zona_id_from_label(destino)}]
            for z in zonas:
                execute("""
                    insert into simoc_mensagens (zona_id, titulo, mensagem, tipo, criada_por)
                    values (:zona, :titulo, :mensagem, 'manual', :uid)
                """, {"zona": z["id"], "titulo": titulo.strip(), "mensagem": msg.strip(), "uid": usuario_logado()["id"]})
            registrar_auditoria("enviar_mensagem", "simoc_mensagens", detalhe=destino)
            st.success(f"Mensagem enviada para {len(zonas)} Zona(s).")
    st.markdown("---")
    df = dataframe("""
        select m.id, z.numero as zona, z.municipio_sede, m.titulo, m.tipo, m.criada_em, m.lida_em
        from simoc_mensagens m left join simoc_zonas z on z.id=m.zona_id
        order by m.criada_em desc limit 200
    """)
    if not df.empty:
        df["criada_em"] = df["criada_em"].apply(fmt_data)
        df["lida_em"] = df["lida_em"].apply(fmt_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def pagina_zonas():
    st.subheader("Zonas Eleitorais, município-sede e e-mail institucional")
    st.caption("O e-mail segue o padrão zona001@tre-ba.jus.br. O município-sede fica registrado no banco local do SIMOC para evitar consulta à internet a cada abertura do sistema.")

    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        if st.button("Garantir e-mails padrão zona001 a zona205", use_container_width=True):
            with get_engine().begin() as conn:
                aplicar_zonas_padrao(conn, usar_tabela_local=False, sobrescrever_municipio=False)
            registrar_auditoria("garantir_emails_zonas", "simoc_zonas")
            st.success("E-mails padronizados atualizados: zona001@tre-ba.jus.br até zona205@tre-ba.jus.br.")
            st.rerun()
    with col_b:
        if st.button("Aplicar tabela local de municípios-sede", use_container_width=True):
            with get_engine().begin() as conn:
                total, aplicados = aplicar_zonas_padrao(conn, usar_tabela_local=True, sobrescrever_municipio=False)
            registrar_auditoria("aplicar_tabela_local_municipios", "simoc_zonas", detalhe=f"{aplicados} sedes aplicadas")
            if aplicados:
                st.success(f"Tabela local aplicada. {aplicados} município(s)-sede preenchido(s); {total} e-mails garantidos.")
            else:
                st.info("A tabela local ainda não tem municípios-sede preenchidos no código. Use a edição manual ou importe uma planilha CSV.")
            st.rerun()
    with col_c:
        st.download_button(
            "Baixar modelo CSV das Zonas",
            data=modelo_csv_zonas(),
            file_name="modelo_zonas_municipio_sede.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("### Importar tabela de município-sede")
    st.caption("Use uma planilha com colunas: numero, municipio_sede e, opcionalmente, email. O sistema grava no Supabase e não precisa consultar a internet depois.")
    arq = st.file_uploader("Importar CSV/XLSX de Zonas", type=["csv", "xlsx"], key="upload_zonas_sede")
    sobrescrever = st.checkbox("Sobrescrever municípios-sede já preenchidos", value=False)
    if arq is not None and st.button("Importar tabela para o sistema", use_container_width=True):
        try:
            if arq.name.lower().endswith(".xlsx"):
                df_imp = pd.read_excel(arq)
            else:
                df_imp = pd.read_csv(arq, sep=None, engine="python")
            with get_engine().begin() as conn:
                qtd = importar_tabela_zonas_csv(conn, df_imp, sobrescrever=sobrescrever)
            registrar_auditoria("importar_tabela_zonas", "simoc_zonas", detalhe=f"{qtd} linhas importadas")
            st.success(f"Tabela importada. {qtd} Zona(s) atualizada(s).")
            st.rerun()
        except Exception as e:
            st.error(f"Não consegui importar a tabela: {e}")

    pendentes = scalar("""
        select count(*) from simoc_zonas
        where municipio_sede is null
           or trim(municipio_sede) = ''
           or municipio_sede in ('Município-sede não informado', 'Município-sede pendente de atualização', 'Município-sede pendente de cadastro', 'Sede não informada')
    """) or 0
    if pendentes:
        st.warning(f"Ainda há {pendentes} Zona(s) sem município-sede registrado. Preencha pela tabela editável abaixo ou importe o CSV oficial/conferido.")

    df = dataframe("select id, numero, nome, municipio_sede, email, ativa from simoc_zonas order by numero")
    if not df.empty:
        df["email_padrao"] = df["numero"].apply(lambda n: email_padrao_zona(int(n)))
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### Editar município-sede diretamente no sistema")
    st.caption("Edite uma Zona por vez. Essas informações ficam salvas no Supabase.")
    with st.expander("Ajustar manualmente uma Zona"):
        with st.form("form_zona"):
            zlabel = st.selectbox("Zona", zona_options())
            atual = None
            zid_atual = zona_id_from_label(zlabel) if zlabel else None
            if zid_atual:
                atual_linhas = rows("select numero, municipio_sede, email from simoc_zonas where id=:id", {"id": zid_atual})
                atual = atual_linhas[0] if atual_linhas else None
            sede = st.text_input("Município-sede", value=(atual.get("municipio_sede") if atual else "") or "")
            numero_sel = int(atual.get("numero") if atual else ((zlabel.split("|")[1].strip()[:3] if "|" in zlabel else "0") or 0))
            email = st.text_input("E-mail da Zona", value=(atual.get("email") if atual else "") or (email_padrao_zona(numero_sel) if numero_sel else ""))
            ok = st.form_submit_button("Salvar dados da Zona")
        if ok:
            zid = zona_id_from_label(zlabel)
            execute("update simoc_zonas set municipio_sede=:sede, email=:email where id=:id", {"sede": sede.strip(), "email": normalizar_email(email), "id": zid})
            registrar_auditoria("atualizar_zona", "simoc_zonas", zid)
            st.success("Zona atualizada.")
            st.rerun()


def pagina_usuarios():
    st.subheader("Usuários")
    df = dataframe("""
        select u.id, u.nome, u.email, u.perfil, z.numero as zona, z.municipio_sede, u.ativo, u.validado, u.ultimo_login, u.criado_em
        from simoc_usuarios u left join simoc_zonas z on z.id=u.zona_id
        order by u.criado_em desc
    """)
    if not df.empty:
        df["ultimo_login"] = df["ultimo_login"].apply(fmt_data)
        df["criado_em"] = df["criado_em"].apply(fmt_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    pendentes = rows("select id, nome, email from simoc_usuarios where validado=false and ativo=true order by criado_em")
    if pendentes:
        st.markdown("### Cadastros pendentes")
        for u in pendentes:
            c1, c2 = st.columns([3,1])
            with c1: st.write(f"{u['nome']} - {u['email']}")
            with c2:
                if st.button("Validar usuário", key=f"valid_user_{u['id']}"):
                    execute("update simoc_usuarios set validado=true, token_validacao=null, atualizado_em=now() where id=:id", {"id": u["id"]})
                    registrar_auditoria("validar_usuario_admin", "simoc_usuarios", u["id"], u["email"])
                    st.success("Usuário validado.")
                    st.rerun()


def gerar_pdf(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elems = [Paragraph("SIMOC-BA - Relatório de Checklists", styles["Title"]), Spacer(1, 12)]
    if df.empty:
        elems.append(Paragraph("Nenhum registro encontrado.", styles["Normal"]))
    else:
        cols = [c for c in ["zona", "municipio_sede", "grupo", "atividade", "periodicidade", "prazo_preenchimento", "status", "responsavel_zona"] if c in df.columns]
        data = [cols] + df[cols].astype(str).values.tolist()[:80]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#123E66")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), .25, colors.grey),
            ("FONTSIZE", (0,0), (-1,-1), 7),
        ]))
        elems.append(table)
    doc.build(elems)
    return buffer.getvalue()


def pagina_relatorios():
    st.subheader("Relatórios com filtros")
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: status = st.selectbox("Status", ["Todos"] + STATUS_CHECKLIST)
    with c2: periodicidade = st.selectbox("Periodicidade", ["Todas"] + PERIODICIDADES)
    with c3: grupo = st.selectbox("Grupo", ["Todos"] + GRUPOS_PADRAO)
    with c4: zlabel = st.selectbox("Zona", zona_options(incluir_todas=True))
    with c5: inicio = st.date_input("Início", value=None, format="DD/MM/YYYY")
    with c6: fim = st.date_input("Fim", value=None, format="DD/MM/YYYY")
    zid = zona_id_from_label(zlabel)
    df = df_checklists_filtrado(status, periodicidade, grupo, zid, inicio, fim)
    st.dataframe(df, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    with col1:
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="checklists")
        st.download_button("Baixar Excel", out.getvalue(), file_name=f"simoc_relatorio_{hoje_brasilia().isoformat()}.xlsx")
    with col2:
        if REPORTLAB_OK:
            st.download_button("Baixar PDF", gerar_pdf(df), file_name=f"simoc_relatorio_{hoje_brasilia().isoformat()}.pdf")
        else:
            st.info("PDF indisponível: reportlab não instalado.")


def pagina_backup():
    st.subheader("Backup e restauração")
    tabelas = ["simoc_zonas", "simoc_usuarios", "simoc_atividades", "simoc_checklists", "simoc_mensagens", "simoc_auditoria"]
    if st.button("Gerar backup JSON completo"):
        data = {"gerado_em": fmt_data(agora_brasilia()), "tabelas": {}}
        for t in tabelas:
            data["tabelas"][t] = rows(f"select * from {t}")
            # converter datas para string
            for row in data["tabelas"][t]:
                for k, v in list(row.items()):
                    if isinstance(v, (datetime, date)):
                        row[k] = fmt_data(v)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        registrar_auditoria("gerar_backup", "backup", detalhe="json")
        st.download_button("Baixar backup", payload, file_name=f"simoc_backup_{hoje_brasilia().isoformat()}.json", mime="application/json")
    st.markdown("---")
    st.warning("Restauração é operação sensível. Faça apenas se tiver certeza e com backup anterior salvo.")
    uploaded = st.file_uploader("Arquivo JSON de backup", type=["json"])
    confirm = st.text_input("Digite CONFIRMO RESTAURAR para habilitar a restauração")
    if uploaded and confirm == "CONFIRMO RESTAURAR" and st.button("Restaurar backup"):
        st.error("Restauração automática foi bloqueada nesta versão para evitar perda acidental. Use o backup para auditoria/exportação ou peça uma rotina assistida de restauração.")


def pagina_auditoria():
    st.subheader("Auditoria")
    df = dataframe("""
        select a.id, u.email as usuario, a.acao, a.entidade, a.entidade_id, a.detalhe, a.criado_em
        from simoc_auditoria a left join simoc_usuarios u on u.id=a.usuario_id
        order by a.criado_em desc limit 500
    """)
    if not df.empty:
        df["criado_em"] = df["criado_em"].apply(fmt_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# PAGINAS ZONA
# ============================================================

def pagina_inicio_zona():
    u = usuario_logado() or {}
    zid = u.get("zona_id")
    atras = scalar("select count(*) from simoc_checklists where zona_id=:z and status in ('pendente','devolvido') and prazo_preenchimento < :h", {"z": zid, "h": hoje_brasilia()}) or 0
    pend = scalar("select count(*) from simoc_checklists where zona_id=:z and status in ('pendente','devolvido')", {"z": zid}) or 0
    msgs = scalar("select count(*) from simoc_mensagens where zona_id=:z and lida_em is null", {"z": zid}) or 0
    c1,c2,c3 = st.columns(3)
    with c1: metric_card("Pendentes/devolvidos", pend)
    with c2: metric_card("Atrasados", atras)
    with c3: metric_card("Mensagens não lidas", msgs)
    if atras:
        alert("danger", "Há checklist em atraso. Regularize ou registre observação para a Corregedoria.")
    c1, c2 = st.columns(2)
    with c1:
        action_card("✅ Checklist da Zona", "Visualizar atividades cadastradas pela Corregedoria, informar responsável local, marcar realização e registrar observações.", "Abrir checklist", "Checklist", nav_key="nav_zona", button_key="zona_home_check")
    with c2:
        action_card("✉️ Mensagens da Corregedoria", "Ler orientações, alertas automáticos de atraso e comunicações enviadas pela Corregedoria.", "Abrir mensagens", "Mensagens", nav_key="nav_zona", button_key="zona_home_msg")


def pagina_checklist_zona():
    u = usuario_logado() or {}
    zid = u.get("zona_id")
    st.subheader("Checklist da Zona")
    itens = rows("""
        select c.id, a.descricao, a.grupo, a.periodicidade, a.orientacao, a.exige_evidencia,
               c.periodo_inicio, c.periodo_fim, c.prazo_preenchimento, c.status,
               c.responsavel_zona, c.realizado, c.data_execucao, c.observacao_zona, c.evidencia_url, c.comentario_corregedoria
        from simoc_checklists c join simoc_atividades a on a.id=c.atividade_id
        where c.zona_id=:z and c.status in ('pendente','devolvido')
        order by c.prazo_preenchimento, a.descricao
    """, {"z": zid})
    if not itens:
        st.info("Não há atividades pendentes para esta Zona.")
        return
    for r in itens:
        atrasado = r["prazo_preenchimento"] < hoje_brasilia()
        titulo = f"{r['descricao']} | {r['periodicidade']} | prazo {fmt_data(r['prazo_preenchimento'])}"
        with st.expander(titulo, expanded=atrasado):
            if atrasado:
                alert("danger", "Prazo vencido. A Corregedoria visualizará esta pendência e o sistema gerará alerta.")
            if r.get("comentario_corregedoria"):
                alert("warn", f"Comentário da Corregedoria: {r['comentario_corregedoria']}")
            st.write(f"**Grupo:** {r['grupo']}")
            st.write(f"**Período de execução:** {fmt_data(r['periodo_inicio'])} a {fmt_data(r['periodo_fim'])}")
            if r.get("orientacao"):
                st.info(r["orientacao"])
            with st.form(f"form_check_{r['id']}"):
                resp = st.text_input("Responsável pela atividade na Zona", value=r.get("responsavel_zona") or "")
                realizado = st.checkbox("Atividade realizada", value=bool(r.get("realizado")))
                data_exec = st.date_input("Data de execução/conferência", value=r.get("data_execucao") or hoje_brasilia(), format="DD/MM/YYYY")
                obs = st.text_area("Observações da Zona", value=r.get("observacao_zona") or "")
                evid = st.text_input("Link da evidência, SEI ou comprovante", value=r.get("evidencia_url") or "")
                enviar = st.form_submit_button("Enviar checklist para a Corregedoria", type="primary")
            if enviar:
                if not resp.strip():
                    st.warning("Informe o responsável pela atividade na Zona.")
                elif not realizado:
                    st.warning("Marque a atividade como realizada ou registre observação justificando antes de enviar.")
                elif r.get("exige_evidencia") and not evid.strip():
                    st.warning("Esta atividade exige evidência/link SEI.")
                else:
                    execute("""
                        update simoc_checklists set responsavel_zona=:resp, realizado=:realizado, data_execucao=:data_exec,
                        observacao_zona=:obs, evidencia_url=:evid, status='em_analise', enviado_em=now(), atualizado_em=now()
                        where id=:id and zona_id=:z
                    """, {"resp": resp.strip(), "realizado": realizado, "data_exec": data_exec, "obs": obs.strip(), "evid": evid.strip(), "id": r["id"], "z": zid})
                    registrar_auditoria("enviar_checklist_zona", "simoc_checklists", r["id"], resp.strip())
                    st.success("Checklist enviado à Corregedoria para visualização/validação.")
                    st.rerun()


def pagina_mensagens_zona():
    u = usuario_logado() or {}
    zid = u.get("zona_id")
    st.subheader("Mensagens da Corregedoria")
    msgs = rows("""
        select id, titulo, mensagem, tipo, criada_em, lida_em
        from simoc_mensagens where zona_id=:z order by criada_em desc limit 200
    """, {"z": zid})
    if not msgs:
        st.info("Não há mensagens para esta Zona.")
        return
    for m in msgs:
        with st.expander(f"{m['titulo']} · {fmt_data(m['criada_em'])} · {m['tipo']}"):
            st.write(m["mensagem"])
            if m.get("lida_em"):
                st.caption(f"Lida em {fmt_data(m['lida_em'])}")
            else:
                if st.button("Marcar como lida", key=f"lida_{m['id']}"):
                    execute("update simoc_mensagens set lida_em=now() where id=:id and zona_id=:z", {"id": m["id"], "z": zid})
                    st.rerun()


# ============================================================
# APP PRINCIPAL
# ============================================================

def app_corregedoria():
    paginas = ["Início", "Atividades", "Acompanhamento", "Validação", "Mensagens", "Zonas", "Relatórios", "Usuários", "Backup", "Auditoria"]
    pagina = nav(paginas, "nav_cor")
    if pagina == "Início": pagina_inicio_corregedoria()
    elif pagina == "Atividades": pagina_atividades()
    elif pagina == "Acompanhamento": pagina_acompanhamento()
    elif pagina == "Validação": pagina_validacao()
    elif pagina == "Mensagens": pagina_mensagens_corregedoria()
    elif pagina == "Zonas": pagina_zonas()
    elif pagina == "Relatórios": pagina_relatorios()
    elif pagina == "Usuários": pagina_usuarios()
    elif pagina == "Backup": pagina_backup()
    elif pagina == "Auditoria": pagina_auditoria()


def app_zona():
    paginas = ["Início", "Checklist", "Mensagens"]
    pagina = nav(paginas, "nav_zona")
    if pagina == "Início": pagina_inicio_zona()
    elif pagina == "Checklist": pagina_checklist_zona()
    elif pagina == "Mensagens": pagina_mensagens_zona()


def main():
    if not usuario_logado():
        tela_login()
        return
    bootstrap_schema_once()
    header()
    col1, col2 = st.columns([8, 1])
    with col1: user_strip()
    with col2:
        if st.button("Sair"):
            registrar_auditoria("logout", "simoc_usuarios", usuario_logado().get("id"))
            st.session_state.clear()
            st.rerun()
    if eh_corregedoria():
        app_corregedoria()
    elif eh_zona():
        app_zona()
    else:
        st.error("Perfil não autorizado.")


if __name__ == "__main__":
    main()
