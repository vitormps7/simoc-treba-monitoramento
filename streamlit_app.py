from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import secrets
import smtplib
import tempfile
from email.message import EmailMessage

import pandas as pd
import streamlit as st
from sqlalchemy import text
from db import db_session, run_schema
from importers import importar_itens_ods
from logo_corregedoria import LOGO_CORREGEDORIA_BASE64
from security import hash_password, verify_password
from treba_importer import importar_zonas, seed_zonas_bahia_padrao, TREBA_CONSULTA_CARTORIOS_URL
from zonas_bahia import ZONAS_BAHIA

st.set_page_config(page_title="SIMOC-BA - Monitoramento Cartorário", page_icon="🛡️", layout="wide")

FUSO_HORARIO_BRASILIA = timezone(timedelta(hours=-3), name="BRT")
FORMATO_DATA_BR = "%d/%m/%Y"
FORMATO_DATA_HORA_BR = "%d/%m/%Y %H:%M"
SQL_AGORA_BRASILIA = "(now() at time zone 'America/Sao_Paulo')"
SQL_HOJE_BRASILIA = "((now() at time zone 'America/Sao_Paulo')::date)"
DOMINIO_INSTITUCIONAL = "@tre-ba.jus.br"
NOME_SISTEMA = "SIMOC-BA"
NOME_COMPLETO = "Sistema de Monitoramento Cartorário das Zonas Eleitorais - TRE-BA"
TRIBUNAL_PADRAO = "TRE-BA"
UF_PADRAO = "BA"
UNIDADE_CORREGEDORIA = "CRE-BA"
TITULO_TELA_INICIAL = "SIMOC-BA - Sistema de Monitoramento Cartorário das Zonas Eleitorais"
SUBTITULO_TELA_INICIAL = "Corregedoria Regional Eleitoral da Bahia · Fiscalização, gestão e orientação das Zonas Eleitorais"

PERFIS = [
    ("admin", "Administra sistema, usuários, zonas, parâmetros, backup e restauração."),
    ("corregedoria_gestor", "Gestão da Corregedoria, dashboards, validações e relatórios."),
    ("corregedoria_analista", "Análise operacional, comentários, validações e relatórios."),
    ("chefe_cartorio", "Responsável pelo preenchimento da própria Zona Eleitoral."),
    ("substituto", "Substituto autorizado para preenchimento da zona vinculada."),
    ("auditor", "Consulta, relatórios e auditoria em modo leitura."),
]

STATUS_TAREFA = ["pendente", "atrasado", "cumprido", "cumprido_com_ressalva", "nao_se_aplica", "em_analise", "validado", "devolvido"]

# ============================================================
# ESTILO E UTILITÁRIOS
# ============================================================

st.markdown(
    """
    <style>
    :root {
        --azul-tre:#174A7C;
        --azul-claro:#EAF3FF;
        --verde:#15803D;
        --amarelo:#F59E0B;
        --vermelho:#B91C1C;
        --cinza:#475569;
    }
    .block-container {padding-top:1.2rem; padding-bottom:2.4rem; max-width: 1500px;}
    section[data-testid="stSidebar"] {background:linear-gradient(180deg,#0F2F52,#174A7C);}
    section[data-testid="stSidebar"] * {color:#FFFFFF !important;}
    section[data-testid="stSidebar"] .stButton button {background:#FFFFFF;color:#174A7C !important;border-radius:12px;border:0;font-weight:800;}
    div[data-testid="stButton"] button {border-radius:10px;font-weight:800;border:1px solid #174A7C;}
    div[data-testid="stButton"] button[kind="primary"] {background:#174A7C;border-color:#174A7C;color:white;}
    .main-header {background:linear-gradient(120deg,#0F2F52,#174A7C 45%,#EAF3FF);padding:18px 22px;border-radius:18px;color:white;margin-bottom:18px;border:1px solid #D7E0EA;display:flex;align-items:center;gap:18px;box-shadow:0 8px 22px rgba(15,47,82,.14);}
    .logo-box {background:white;border-radius:14px;padding:10px;box-shadow:0 2px 8px rgba(0,0,0,.08);}
    .logo-box img {max-width:170px;max-height:66px;object-fit:contain;}
    .main-header h1 {font-size:25px;margin:0 0 5px 0;color:white;line-height:1.25;}
    .main-header p {font-size:13px;margin:3px 0;color:#EAF3FF;}
    .hero-caption {font-size:12px;background:rgba(255,255,255,.16);padding:5px 9px;border-radius:999px;display:inline-block;margin-top:6px;}
    .metric-card {background:white;border:1px solid #D7E0EA;border-left:5px solid #174A7C;border-radius:14px;padding:13px 14px;min-height:104px;box-shadow:0 4px 12px rgba(15,47,82,.07);}
    .metric-card .metric-top {display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
    .metric-card .icon {font-size:26px;line-height:1;}
    .metric-card .label {font-size:12px;font-weight:800;color:#4B5563;text-transform:uppercase;letter-spacing:.03em;}
    .metric-card .value {font-size:28px;font-weight:900;color:#174A7C;}
    .section-title {background:#174A7C;color:white;padding:10px 13px;border-radius:10px;margin:18px 0 10px 0;font-weight:900;box-shadow:0 4px 12px rgba(23,74,124,.18);}
    .status-pill {border-radius:999px;padding:4px 10px;color:white;font-weight:800;font-size:12px;display:inline-block;}
    .action-card {background:#FFFFFF;border:1px solid #D7E0EA;border-radius:14px;padding:16px;min-height:142px;box-shadow:0 5px 14px rgba(15,47,82,.06);}
    .action-card .bigicon {font-size:32px;margin-bottom:8px;}
    .action-card h3 {color:#174A7C;font-size:17px;margin:0 0 6px 0;}
    .action-card p {color:#475569;font-size:13px;margin:0;line-height:1.35;}
    .alert-card {border-radius:14px;padding:13px 14px;margin:8px 0;border:1px solid #FCD34D;background:#FFFBEB;color:#78350F;}
    .alert-card.danger {border-color:#FCA5A5;background:#FEF2F2;color:#7F1D1D;}
    .alert-card.ok {border-color:#BBF7D0;background:#F0FDF4;color:#14532D;}
    .guide-box {border-left:5px solid #174A7C;background:#F8FAFC;border-radius:12px;padding:14px 16px;margin:10px 0;}
    .guide-box h4 {margin:0 0 5px 0;color:#174A7C;}
    .guide-box p {margin:0;color:#475569;font-size:14px;}
    div[data-testid="stDataFrame"] {border:1px solid #D7E0EA;border-radius:12px;overflow:hidden;}

    .module-grid-title {font-size:18px;font-weight:900;color:#174A7C;margin:18px 0 10px 0;}
    .module-card {background:#FFFFFF;border:1.5px solid #1D4ED8;border-radius:10px;padding:18px 18px 12px 18px;text-align:center;min-height:255px;box-shadow:0 8px 20px rgba(29,78,216,.06);display:flex;flex-direction:column;align-items:center;justify-content:flex-start;}
    .module-card:hover {transform:translateY(-2px);box-shadow:0 14px 28px rgba(29,78,216,.12);transition:all .16s ease-in-out;}
    .module-icon {width:86px;height:86px;border:3px solid #005EB8;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:39px;color:#005EB8;margin:4px auto 16px auto;background:#F8FBFF;}
    .module-card h3 {font-size:21px;line-height:1.28;margin:4px 0 12px 0;color:#424B57;font-weight:900;}
    .module-card p {font-size:14px;line-height:1.35;color:#475569;margin:0 auto 10px auto;max-width:310px;}
    .module-card .mini {font-size:12px;color:#64748B;margin-top:8px;background:#F1F5F9;border-radius:999px;padding:4px 9px;}
    .quick-btn button {width:100%;background:#005EB8 !important;color:white !important;border:0 !important;border-radius:8px !important;padding:.62rem 1rem !important;font-size:15px !important;}
    .workflow-card {background:#FFFFFF;border:1px solid #D7E0EA;border-radius:14px;padding:16px;min-height:122px;box-shadow:0 5px 12px rgba(15,47,82,.06);}
    .workflow-card h4 {font-size:16px;color:#174A7C;margin:0 0 7px 0;}
    .workflow-card p {font-size:13px;color:#475569;margin:0;line-height:1.35;}
    .plan-chip {display:inline-block;margin:4px 5px 4px 0;padding:6px 10px;border-radius:999px;background:#EAF3FF;border:1px solid #BFDBFE;color:#174A7C;font-weight:800;font-size:12px;}
    .risk-strip {border-left:7px solid #B91C1C;background:#FEF2F2;border-radius:12px;padding:13px 15px;margin:10px 0;color:#7F1D1D;}
    .orientation-strip {border-left:7px solid #005EB8;background:#EFF6FF;border-radius:12px;padding:13px 15px;margin:10px 0;color:#174A7C;}
    .auth-hero {background:#DCE7F3;border:1px solid #C6D2E1;border-radius:18px;padding:28px 24px 26px 24px;margin-bottom:18px;box-shadow:0 4px 16px rgba(15,47,82,.06);}
    .auth-logo-band {background:linear-gradient(90deg,#EEF4FB 0%, #F8FAFD 100%);border-radius:18px;padding:18px 26px;display:flex;align-items:center;justify-content:center;min-height:150px;margin:0 auto 20px auto;max-width:820px;box-shadow:inset 0 0 0 1px rgba(23,74,124,.05);}
    .auth-logo-band img {max-width:100%;width:min(760px, 92%);max-height:140px;object-fit:contain;display:block;}
    .auth-title {text-align:center;font-size:25px;line-height:1.28;font-weight:900;color:#174A7C;margin:6px 0 8px 0;}
    .auth-subtitle {text-align:center;font-size:14px;line-height:1.5;color:#415466;margin:0 auto;max-width:980px;}
    .auth-panel {background:#FFFFFF;border:1px solid #E5EAF1;border-radius:18px;padding:22px 24px 18px 24px;box-shadow:0 6px 18px rgba(15,47,82,.05);margin-top:10px;}
    .auth-heading {font-size:20px;font-weight:900;color:#1E3A5F;margin:4px 0 14px 0;}
    .auth-helper {font-size:13px;color:#64748B;margin:-4px 0 14px 0;}
    div[data-testid="stTabs"] > div:first-child {gap:28px;}
    div[data-testid="stTabs"] button[role="tab"] {height:44px;padding:0 4px;border-radius:0;border-bottom:2px solid transparent;font-weight:700;color:#475569;}
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {color:#EF4444;border-bottom:3px solid #EF4444;}
    div[data-testid="stTabs"] button[role="tab"] p {font-size:15px;}
    div[data-testid="stForm"] {background:#FFFFFF;}
    .auth-button-tip {font-size:12px;color:#64748B;margin-top:6px;}
    div[role="radiogroup"] label {font-weight:800;}

    .interface-banner {border-radius:18px;padding:20px 22px;margin:10px 0 18px 0;border:1px solid #D7E0EA;box-shadow:0 8px 20px rgba(15,47,82,.06);}
    .interface-banner.corregedoria {background:linear-gradient(120deg,#0F2F52,#174A7C);color:white;}
    .interface-banner.zona {background:linear-gradient(120deg,#EAF3FF,#FFFFFF);color:#174A7C;border-left:7px solid #174A7C;}
    .interface-banner h2 {margin:0 0 6px 0;font-size:26px;font-weight:900;}
    .interface-banner p {margin:3px 0;font-size:14px;line-height:1.45;}
    .interface-card {background:white;border:1px solid #D7E0EA;border-radius:16px;padding:18px;min-height:156px;box-shadow:0 6px 16px rgba(15,47,82,.06);}
    .interface-card h3 {font-size:18px;color:#174A7C;margin:0 0 8px 0;font-weight:900;}
    .interface-card p {font-size:13px;color:#475569;margin:0 0 12px 0;line-height:1.4;}
    .step-flow {display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 16px 0;}
    .step-flow span {background:#EAF3FF;border:1px solid #BFDBFE;color:#174A7C;border-radius:999px;padding:8px 12px;font-weight:800;font-size:13px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def agora_brasilia() -> datetime:
    return datetime.now(timezone.utc).astimezone(FUSO_HORARIO_BRASILIA).replace(microsecond=0)


def agora_iso() -> str:
    return agora_brasilia().isoformat()


def agora_texto() -> str:
    return agora_brasilia().strftime(FORMATO_DATA_HORA_BR)


def data_texto(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    if isinstance(valor, datetime):
        dt = valor
        if dt.tzinfo is not None:
            dt = dt.astimezone(FUSO_HORARIO_BRASILIA)
        return dt.strftime(FORMATO_DATA_BR)
    if isinstance(valor, date):
        return valor.strftime(FORMATO_DATA_BR)
    try:
        dt = pd.to_datetime(valor)
        if pd.isna(dt):
            return ""
        return dt.strftime(FORMATO_DATA_BR)
    except Exception:
        return str(valor)


def data_hora_texto(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    try:
        dt = pd.to_datetime(valor)
        if pd.isna(dt):
            return ""
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.tz_convert(FUSO_HORARIO_BRASILIA) if hasattr(dt, "tz_convert") else dt.astimezone(FUSO_HORARIO_BRASILIA)
        return dt.strftime(FORMATO_DATA_HORA_BR)
    except Exception:
        return str(valor)


def formatar_dataframe_datas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    colunas_data = {"prazo", "periodo_inicio", "periodo_fim", "início ciclo", "fim ciclo", "data_de", "data_ate"}
    palavras_data = ["prazo", "início ciclo", "fim ciclo", "periodo_inicio", "periodo_fim"]
    palavras_data_hora = ["criado", "criada", "enviado", "envio", "atualizado", "validado", "último", "ultimo", "login", "data", "emissão"]
    for col in out.columns:
        nome = str(col).strip().lower()
        if nome in colunas_data or any(p in nome for p in palavras_data):
            out[col] = out[col].apply(data_texto)
        elif any(p in nome for p in palavras_data_hora):
            out[col] = out[col].apply(data_hora_texto)
    return out


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def email_institucional(email: str) -> bool:
    return normalizar_email(email).endswith(DOMINIO_INSTITUCIONAL)


def app_base_url() -> str:
    try:
        return st.secrets.get("APP_BASE_URL", "").rstrip("/")
    except Exception:
        return os.getenv("APP_BASE_URL", "").rstrip("/")


def enviar_email(destinatario: str, assunto: str, corpo: str) -> tuple[bool, str]:
    try:
        smtp_host = st.secrets.get("SMTP_HOST", "")
        smtp_port = int(st.secrets.get("SMTP_PORT", 587))
        smtp_user = st.secrets.get("SMTP_USER", "")
        smtp_password = st.secrets.get("SMTP_PASSWORD", "")
        remetente = st.secrets.get("EMAIL_REMETENTE", smtp_user)
        if not all([smtp_host, smtp_port, smtp_user, smtp_password, remetente]):
            return False, "Envio de e-mail não configurado nos Secrets do Streamlit."
        msg = EmailMessage()
        msg["From"] = remetente
        msg["To"] = destinatario
        msg["Subject"] = assunto
        msg.set_content(corpo)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as servidor:
            servidor.starttls()
            servidor.login(smtp_user, smtp_password)
            servidor.send_message(msg)
        return True, "E-mail enviado com sucesso."
    except Exception as exc:
        return False, f"Não foi possível enviar o e-mail: {exc}"


def get_query_param(nome: str):
    try:
        valor = st.query_params.get(nome)
        if isinstance(valor, list):
            return valor[0] if valor else None
        return valor
    except Exception:
        return None


def usuario_logado() -> dict:
    return st.session_state.get("user", {})


def perfil_atual() -> str:
    return usuario_logado().get("perfil", "")


def eh_admin() -> bool:
    return perfil_atual() == "admin"


def eh_corregedoria() -> bool:
    return perfil_atual() in ["admin", "corregedoria_gestor", "corregedoria_analista"]


def eh_zona() -> bool:
    return perfil_atual() in ["chefe_cartorio", "substituto"]


def pode_relatorio() -> bool:
    return perfil_atual() in ["admin", "corregedoria_gestor", "corregedoria_analista", "auditor"]


def status_badge(status: str) -> str:
    mapa = {
        "pendente": "#F59E0B", "atrasado": "#B91C1C", "cumprido": "#2563EB",
        "cumprido_com_ressalva": "#7A60A8", "nao_se_aplica": "#64748B",
        "em_analise": "#0F766E", "validado": "#15803D", "devolvido": "#C2410C",
    }
    cor = mapa.get(status, "#475569")
    return f"<span class='status-pill' style='background:{cor};'>{status}</span>"


def html_action_card(icone: str, titulo: str, texto: str) -> str:
    return f"""
    <div class='action-card'>
        <div class='bigicon'>{icone}</div>
        <h3>{titulo}</h3>
        <p>{texto}</p>
    </div>
    """

def st_action_card(icone: str, titulo: str, texto: str):
    st.markdown(html_action_card(icone, titulo, texto), unsafe_allow_html=True)

def st_alerta(tipo: str, titulo: str, texto: str):
    classe = {'risco':'danger','ok':'ok','atenção':''}.get(tipo, '')
    icone = {'risco':'🚨','ok':'✅','atenção':'⚠️'}.get(tipo, 'ℹ️')
    st.markdown(f"<div class='alert-card {classe}'><b>{icone} {titulo}</b><br>{texto}</div>", unsafe_allow_html=True)

def titulo_secao(icone: str, texto: str):
    st.markdown(f"<div class='section-title'>{icone} {texto}</div>", unsafe_allow_html=True)


def module_card_html(icone: str, titulo: str, texto: str, detalhe: str = "") -> str:
    mini = f"<div class='mini'>{detalhe}</div>" if detalhe else ""
    return f"""
    <div class='module-card'>
        <div class='module-icon'>{icone}</div>
        <h3>{titulo}</h3>
        <p>{texto}</p>
        {mini}
    </div>
    """

def nav_button(label: str, destino: str, key: str):
    st.markdown("<div class='quick-btn'>", unsafe_allow_html=True)
    clicked = st.button(label, key=key, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    if clicked:
        st.session_state.nav_target = destino
        st.rerun()

def workflow_card(icone: str, titulo: str, texto: str):
    st.markdown(f"<div class='workflow-card'><h4>{icone} {titulo}</h4><p>{texto}</p></div>", unsafe_allow_html=True)

def planilha_chips(itens: list[str]):
    st.markdown("".join([f"<span class='plan-chip'>{i}</span>" for i in itens]), unsafe_allow_html=True)


# ============================================================
# BANCO, AUDITORIA E DADOS
# ============================================================


def scalar(sql: str, **params):
    with db_session() as conn:
        return conn.execute(text(sql), params).scalar()


@st.cache_data(ttl=90, show_spinner=False)
def _dataframe_cached(sql: str, params_json: str) -> pd.DataFrame:
    params = json.loads(params_json) if params_json else {}
    with db_session() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


def dataframe(sql: str, use_cache: bool = True, **params) -> pd.DataFrame:
    # Cache curto para dashboards/listas. Mantem o app responsivo sem deixar
    # dados operacionais presos por muito tempo.
    if use_cache:
        params_json = json.dumps(params, sort_keys=True, default=str)
        return formatar_dataframe_datas(_dataframe_cached(sql, params_json))
    with db_session() as conn:
        return formatar_dataframe_datas(pd.read_sql_query(text(sql), conn, params=params))


def limpar_cache_dados():
    try:
        _dataframe_cached.clear()
    except Exception:
        pass
    try:
        zonas_options_cached.clear()
    except Exception:
        pass


def execute(sql: str, **params):
    with db_session() as conn:
        result = conn.execute(text(sql), params)
    limpar_cache_dados()
    return result


def registrar_auditoria(acao: str, entidade: str, entidade_id=None, campo: str = "", anterior: str = "", novo: str = "", detalhe: str = ""):
    u = usuario_logado()
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    insert into logs_auditoria
                    (usuario_id, usuario_nome, usuario_email, acao, entidade, entidade_id, campo, valor_anterior, valor_novo, detalhe, criado_em)
                    values (:uid, :nome, :email, :acao, :entidade, :entidade_id, :campo, :anterior, :novo, :detalhe, (now() at time zone 'America/Sao_Paulo'))
                    """
                ),
                {
                    "uid": u.get("id"), "nome": u.get("nome"), "email": u.get("email"),
                    "acao": acao, "entidade": entidade, "entidade_id": entidade_id,
                    "campo": campo, "anterior": str(anterior or ""), "novo": str(novo or ""), "detalhe": detalhe,
                },
            )
    except Exception:
        pass


@st.cache_resource(ttl=3600, show_spinner=False)
def inicializar_banco_uma_vez(admin_email: str, admin_password_hash: str) -> bool:
    """Executa apenas a inicializacao essencial, no maximo uma vez por hora por processo.

    Antes, cada sessao de usuario chamava run_schema(), o que deixava o
    primeiro carregamento lento no Streamlit Cloud. Agora a verificacao do
    schema, perfis e usuario administrador fica em cache de recurso.

    A funcao NAO importa zonas, NAO importa municipios, NAO importa planilha e
    NAO gera tarefas. Essas acoes continuam manuais na pagina Importacao.
    """
    run_schema()
    with db_session() as conn:
        for nome, descricao in PERFIS:
            conn.execute(
                text("insert into perfis (nome, descricao) values (:nome, :descricao) on conflict (nome) do update set descricao=excluded.descricao"),
                {"nome": nome, "descricao": descricao},
            )

        perfil_id = conn.execute(text("select id from perfis where nome='admin'")).scalar_one()
        exists = conn.execute(text("select id from usuarios where email=:email"), {"email": normalizar_email(admin_email)}).scalar()
        if not exists:
            conn.execute(
                text("""
                    insert into usuarios (nome, email, senha_hash, perfil_id, ativo, validado, secao_operador)
                    values (:nome, :email, :senha, :perfil_id, true, true, :secao)
                """),
                {"nome": "Administrador", "email": normalizar_email(admin_email), "senha": admin_password_hash, "perfil_id": perfil_id, "secao": UNIDADE_CORREGEDORIA},
            )
    return True


def bootstrap_minimo():
    """Inicializacao leve do aplicativo.

    NAO importa zonas, NAO importa municipios, NAO importa planilha e NAO gera
    tarefas. A verificacao do schema/perfis/admin fica cacheada para evitar
    lentidao a cada nova sessao do Streamlit.
    """
    if st.session_state.get("bootstrap_ok"):
        return

    admin_email = st.secrets.get("ADMIN_EMAIL", os.getenv("ADMIN_EMAIL", "admin@tre-ba.jus.br"))
    admin_password = str(st.secrets.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "admin123")))
    inicializar_banco_uma_vez(normalizar_email(admin_email), hash_password(admin_password))
    st.session_state.bootstrap_ok = True


def garantir_banco_para_acao() -> bool:
    """Inicializa banco somente quando o usuario executa uma acao que precisa dele.

    A tela inicial nao chama esta funcao, para abrir rapido no Streamlit Cloud.
    """
    try:
        bootstrap_minimo()
        return True
    except Exception as exc:
        st.error("Nao foi possivel conectar ao Supabase. Confira DATABASE_URL nos Secrets do Streamlit.")
        st.exception(exc)
        return False


@st.cache_data(ttl=300, show_spinner=False)
def zonas_options_cached() -> list[str]:
    df = dataframe("select id, numero, municipio_sede, uf from zonas_eleitorais where ativa=true order by numero")
    if df.empty:
        return ZONAS_BAHIA
    opcoes = []
    for r in df.itertuples():
        sede = r.municipio_sede if r.municipio_sede and r.municipio_sede != "A definir" else "Bahia"
        opcoes.append(f"{int(r.id)} - {int(r.numero):03d}ª ZE - {sede}/{r.uf or 'BA'}")
    return opcoes


def zonas_options(incluir_nenhuma=True) -> list[str]:
    opcoes = zonas_options_cached()
    return (["Nenhuma"] + opcoes) if incluir_nenhuma else opcoes


def zona_id_from_label(label: str):
    if not label or label == "Nenhuma" or label == "Não informado":
        return None
    try:
        return int(str(label).split(" - ")[0])
    except Exception:
        return None


# ============================================================
# AUTENTICAÇÃO, CADASTRO E RECUPERAÇÃO
# ============================================================


def gerar_link_validacao(token: str) -> str:
    base = app_base_url()
    return f"{base}/?validar={token}" if base else f"?validar={token}"


def gerar_link_recuperacao(token: str) -> str:
    base = app_base_url()
    return f"{base}/?recuperar={token}" if base else f"?recuperar={token}"


def processar_validacao():
    token = get_query_param("validar")
    if not token:
        return
    with db_session() as conn:
        row = conn.execute(text("select id from usuarios where token_validacao=:token"), {"token": token}).mappings().first()
        if row:
            conn.execute(text("update usuarios set validado=true, ativo=true, token_validacao=null, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"id": row["id"]})
            st.success("Cadastro validado com sucesso. Faça login para acessar o sistema.")
            registrar_auditoria("validacao_cadastro", "usuarios", row["id"])
        else:
            st.error("Link de validação inválido ou expirado.")


def processar_recuperacao():
    token = get_query_param("recuperar")
    if not token:
        return False
    with db_session() as conn:
        row = conn.execute(
            text("select id, email from usuarios where token_recuperacao=:token and (token_recuperacao_expira_em is null or token_recuperacao_expira_em > (now() at time zone 'America/Sao_Paulo'))"),
            {"token": token},
        ).mappings().first()
    if not row:
        st.error("Link de recuperação inválido ou expirado.")
        return True
    st.subheader("Redefinir senha")
    nova = st.text_input("Nova senha", type="password")
    confirmar = st.text_input("Confirmar nova senha", type="password")
    if st.button("Salvar nova senha", type="primary"):
        if len(nova or "") < 6:
            st.warning("A senha deve ter pelo menos 6 caracteres.")
        elif nova != confirmar:
            st.warning("As senhas não conferem.")
        else:
            with db_session() as conn:
                conn.execute(text("update usuarios set senha_hash=:h, token_recuperacao=null, token_recuperacao_expira_em=null, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"h": hash_password(str(nova)[:72]), "id": row["id"]})
            registrar_auditoria("recuperacao_senha", "usuarios", row["id"], detalhe=row["email"])
            st.success("Senha redefinida com sucesso. Faça login novamente.")
    return True


def login_box():
    st.markdown(
        f"""
        <div class="auth-hero">
            <div class="auth-logo-band">
                <img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}" alt="Logo da Corregedoria Regional Eleitoral da Bahia">
            </div>
            <div class="auth-title">{TITULO_TELA_INICIAL}</div>
            <div class="auth-subtitle">{SUBTITULO_TELA_INICIAL}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # IMPORTANTE PARA PERFORMANCE:
    # A tela inicial NAO consulta o Supabase automaticamente.
    # A conexao so e aberta quando o usuario clica em Entrar, Cadastrar ou Recuperar.
    modo = st.radio("Acesso", ["Entrar", "Cadastrar usuário", "Recuperar senha"], horizontal=True, label_visibility="collapsed")

    if modo == "Entrar":
        st.markdown('<div class="auth-panel">', unsafe_allow_html=True)
        st.markdown('<div class="auth-heading">Acesso ao sistema</div>', unsafe_allow_html=True)
        with st.form("login"):
            email = normalizar_email(st.text_input("E-mail"))
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary")
        st.markdown('<div class="auth-button-tip">A conexao com o banco sera feita apenas apos clicar em Entrar.</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        if submitted:
            if not garantir_banco_para_acao():
                return
            with db_session() as conn:
                row = conn.execute(
                    text("""
                    select u.id, u.nome, u.email, u.senha_hash, u.zona_eleitoral_id, p.nome as perfil, u.validado
                    from usuarios u join perfis p on p.id = u.perfil_id
                    where u.email=:email and u.ativo = true
                    """),
                    {"email": email},
                ).mappings().first()
                if row and row["validado"] and verify_password(senha, row["senha_hash"]):
                    conn.execute(text("update usuarios set ultimo_login=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"id": row["id"]})
                    st.session_state.user = {k: v for k, v in dict(row).items() if k != "senha_hash"}
                    registrar_auditoria("login", "usuarios", row["id"], detalhe=email)
                    st.rerun()
                elif row and not row["validado"]:
                    st.warning("Cadastro ainda não validado. Verifique o link enviado ao e-mail ou solicite validação ao administrador.")
                else:
                    st.error("Usuário ou senha inválidos.")

    elif modo == "Cadastrar usuário":
        if not garantir_banco_para_acao():
            return
        st.markdown('<div class="auth-panel">', unsafe_allow_html=True)
        st.markdown('<div class="auth-heading">Cadastrar usuário</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-helper">Cadastro institucional. Novos usuários ficam pendentes de validação quando o e-mail SMTP estiver configurado.</div>', unsafe_allow_html=True)
        with st.form("auto_cadastro"):
            nome = st.text_input("Nome completo")
            email = normalizar_email(st.text_input("E-mail institucional", key="cad_email"))
            zona_label = st.selectbox("Zona vinculada, se for Chefe/Substituto", zonas_options())
            senha = st.text_input("Senha", type="password", key="cad_senha")
            confirmar = st.text_input("Confirmar senha", type="password")
            submitted = st.form_submit_button("Cadastrar")
        st.markdown('</div>', unsafe_allow_html=True)
        if submitted:
            if not nome.strip():
                st.warning("Informe o nome.")
            elif not email_institucional(email):
                st.warning(f"O e-mail deve terminar com {DOMINIO_INSTITUCIONAL}.")
            elif len(senha or "") < 6:
                st.warning("A senha deve ter pelo menos 6 caracteres.")
            elif senha != confirmar:
                st.warning("As senhas não conferem.")
            else:
                token = secrets.token_urlsafe(32)
                zona_id = zona_id_from_label(zona_label)
                with db_session() as conn:
                    perfil_id = conn.execute(text("select id from perfis where nome='chefe_cartorio'")).scalar_one()
                    existe = conn.execute(text("select id from usuarios where email=:email"), {"email": email}).scalar()
                    if existe:
                        st.warning("Este e-mail já está cadastrado.")
                    else:
                        result = conn.execute(
                            text("""
                            insert into usuarios (nome, email, senha_hash, perfil_id, zona_eleitoral_id, ativo, validado, token_validacao, secao_operador)
                            values (:nome, :email, :senha, :perfil, :zona, true, false, :token, :secao)
                            returning id
                            """),
                            {"nome": nome.strip(), "email": email, "senha": hash_password(str(senha)[:72]), "perfil": perfil_id, "zona": zona_id, "token": token, "secao": UNIDADE_CORREGEDORIA},
                        )
                        user_id = result.scalar_one()
                        link = gerar_link_validacao(token)
                        ok, msg = enviar_email(email, f"Validação de cadastro - {NOME_SISTEMA}", f"Olá, {nome}.\n\nAcesse o link para validar seu cadastro no {NOME_SISTEMA}:\n\n{link}\n\nCaso não tenha solicitado, ignore esta mensagem.")
                        registrar_auditoria("cadastro_usuario", "usuarios", user_id, detalhe=email)
                        if ok:
                            st.success("Cadastro realizado. Link de validação enviado ao e-mail informado.")
                        else:
                            st.warning(f"{msg} Link de validação gerado: {link}")

    else:
        if not garantir_banco_para_acao():
            return
        st.markdown('<div class="auth-panel">', unsafe_allow_html=True)
        st.markdown('<div class="auth-heading">Recuperar senha</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-helper">Informe o e-mail cadastrado para gerar um link de redefinição de senha.</div>', unsafe_allow_html=True)
        email_rec = normalizar_email(st.text_input("E-mail cadastrado", key="rec_email"))
        if st.button("Gerar link de recuperação"):
            with db_session() as conn:
                row = conn.execute(text("select id, nome from usuarios where email=:email and ativo=true"), {"email": email_rec}).mappings().first()
                if not row:
                    st.error("E-mail não encontrado.")
                else:
                    token = secrets.token_urlsafe(32)
                    expira = agora_brasilia() + timedelta(hours=2)
                    conn.execute(text("update usuarios set token_recuperacao=:token, token_recuperacao_expira_em=:expira where id=:id"), {"token": token, "expira": expira.replace(tzinfo=None), "id": row["id"]})
                    link = gerar_link_recuperacao(token)
                    ok, msg = enviar_email(email_rec, f"Recuperação de senha - {NOME_SISTEMA}", f"Olá.\n\nAcesse o link para criar uma nova senha:\n\n{link}\n\nO link expira em 2 horas.")
                    registrar_auditoria("gerar_recuperacao_senha", "usuarios", row["id"], detalhe=email_rec)
                    if ok:
                        st.success("Link de recuperação enviado ao e-mail informado.")
                    else:
                        st.warning(f"{msg} Link de recuperação de senha gerado: {link}")
        st.markdown('</div>', unsafe_allow_html=True)


def cabecalho():
    u = usuario_logado()
    st.markdown(
        f"""
        <div class="main-header">
            <div class="logo-box"><img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}"></div>
            <div>
                <h1>🛡️ {NOME_SISTEMA} - Fiscalização e Orientação das Zonas Eleitorais</h1>
                <p>{NOME_COMPLETO}</p>
                <p>Corregedoria Regional Eleitoral da Bahia | Gestão de conformidade, prazos e evidências</p>
                <span class="hero-caption">Usuário: {u.get('nome','')} · Perfil: {u.get('perfil','')}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_user():
    perfil = perfil_atual()
    st.sidebar.markdown("### 🛡️ SIMOC-BA")
    if eh_zona():
        st.sidebar.markdown("Interface da Zona Eleitoral")
        st.sidebar.caption("A Zona visualiza as tarefas recebidas, executa o checklist e envia as evidências para análise da Corregedoria.")
    elif eh_corregedoria():
        st.sidebar.markdown("Interface da Corregedoria")
        st.sidebar.caption("A Corregedoria cadastra itens, gera tarefas, acompanha prazos, valida respostas e orienta as Zonas.")
    else:
        st.sidebar.markdown("Consulta e relatório")
        st.sidebar.caption("Perfil de leitura para acompanhamento e auditoria.")
    st.sidebar.divider()
    st.sidebar.success(f"👤 {usuario_logado().get('nome')}\n\n🔐 Perfil: {perfil}")
    if st.sidebar.button("🚪 Sair do sistema"):
        registrar_auditoria("logout", "usuarios", usuario_logado().get("id"))
        st.session_state.clear()
        st.rerun()





def page_inicio_corregedoria():
    st.markdown("""
    <div class='interface-banner corregedoria'>
        <h2>🛡️ Interface da Corregedoria</h2>
        <p><b>Função da Corregedoria:</b> cadastrar o que deve ser fiscalizado, gerar tarefas para as Zonas, acompanhar prazos, validar respostas e orientar correções.</p>
        <p>As tarefas nascem aqui. Depois, cada Zona acessa sua própria interface para executar o checklist.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='step-flow'><span>1. Cadastrar plano</span><span>2. Gerar tarefas</span><span>3. Zonas executam</span><span>4. Validar/devolver</span><span>5. Relatar</span></div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='interface-card'><h3>📌 Plano de ação</h3><p>Conferir os itens da planilha inicial: ELO, Sistemas da Intranet e observações críticas.</p></div>", unsafe_allow_html=True)
        nav_button("Abrir plano", "📌 Plano de ação", "home_cor_plano")
    with c2:
        st.markdown("<div class='interface-card'><h3>⚙️ Gerar tarefas</h3><p>Criar ciclos de monitoramento e distribuir tarefas para todas as Zonas Eleitorais.</p></div>", unsafe_allow_html=True)
        nav_button("Cadastrar/gerar tarefas", "⚙️ Cadastrar tarefas", "home_cor_tarefas")
    with c3:
        st.markdown("<div class='interface-card'><h3>🔎 Validar respostas</h3><p>Analisar o checklist enviado pela Zona, validar, devolver ou colocar em análise.</p></div>", unsafe_allow_html=True)
        nav_button("Validar checklist", "🔎 Validar checklist", "home_cor_validar")

    c4, c5, c6 = st.columns(3)
    with c4:
        st.markdown("<div class='interface-card'><h3>📊 Painel gerencial</h3><p>Acompanhar pendências, atrasos, itens críticos e evolução das Zonas.</p></div>", unsafe_allow_html=True)
        nav_button("Ver painel", "📊 Painel da Corregedoria", "home_cor_painel")
    with c5:
        st.markdown("<div class='interface-card'><h3>🧭 Orientar Zonas</h3><p>Usar modelos de comunicação para pendência, devolução e validação.</p></div>", unsafe_allow_html=True)
        nav_button("Orientações", "🧭 Orientações às Zonas", "home_cor_orienta")
    with c6:
        st.markdown("<div class='interface-card'><h3>📄 Relatórios</h3><p>Emitir relatórios para gestão, auditoria e acompanhamento pela Corregedoria.</p></div>", unsafe_allow_html=True)
        nav_button("Emitir relatório", "📄 Relatórios", "home_cor_relat")


def page_inicio_zona():
    st.markdown("""
    <div class='interface-banner zona'>
        <h2>🏛️ Interface da Zona Eleitoral</h2>
        <p><b>Função da Zona:</b> visualizar tarefas recebidas, executar a rotina cartorária e marcar o checklist.</p>
        <p>A Zona não cria o plano de fiscalização. Ela responde às tarefas distribuídas pela Corregedoria.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='step-flow'><span>1. Abrir checklist</span><span>2. Executar tarefa</span><span>3. Marcar status</span><span>4. Anexar evidência</span><span>5. Enviar</span></div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='interface-card'><h3>✅ Meu checklist</h3><p>Ver tarefas pendentes, atrasadas ou devolvidas e enviar resposta para a Corregedoria.</p></div>", unsafe_allow_html=True)
        nav_button("Abrir checklist", "✅ Checklist da Zona", "home_zona_check")
    with c2:
        st.markdown("<div class='interface-card'><h3>📌 Plano de ação</h3><p>Consultar a origem das tarefas: ELO, Sistemas da Intranet e observações da planilha inicial.</p></div>", unsafe_allow_html=True)
        nav_button("Consultar plano", "📌 Plano de ação", "home_zona_plano")
    with c3:
        st.markdown("<div class='interface-card'><h3>🧭 Orientações</h3><p>Consultar orientações gerais da Corregedoria para preenchimento do checklist.</p></div>", unsafe_allow_html=True)
        nav_button("Ver orientações", "🧭 Orientações", "home_zona_orienta")


# ============================================================
# DASHBOARD E MONITORAMENTO
# ============================================================


def render_metric(label, value, color="#174A7C", icon="📊"):
    st.markdown(
        f"<div class='metric-card' style='border-left-color:{color};'><div class='metric-top'><div class='label'>{label}</div><div class='icon'>{icon}</div></div><div class='value' style='color:{color};'>{value}</div></div>",
        unsafe_allow_html=True,
    )


def atualizar_atrasos_manual():
    """Atualiza atrasos apenas quando o usuario pedir.

    O dashboard nao executa UPDATE automaticamente, porque escrita no banco a
    cada abertura deixava o app mais lento. As metricas ja consideram como
    atrasadas as tarefas pendentes com prazo anterior a data de Brasilia.
    """
    with db_session() as conn:
        conn.execute(text("update tarefas_zona set status='atrasado', atualizado_em=(now() at time zone 'America/Sao_Paulo') where prazo < ((now() at time zone 'America/Sao_Paulo')::date) and status='pendente'"))
    limpar_cache_dados()


def page_dashboard():
    st.header("📊 Painel de fiscalização")
    st.caption("Visão executiva para fiscalizar cumprimento, priorizar riscos e orientar as Zonas Eleitorais.")
    if st.button("🔄 Atualizar atrasos agora", help="Use quando quiser gravar no banco as tarefas pendentes cujo prazo já venceu."):
        atualizar_atrasos_manual()
        st.success("Atrasos atualizados com base na data de Brasília.")

    df = dataframe(
        """
        select
          count(*) filter (where status = 'pendente' and (prazo is null or prazo >= ((now() at time zone 'America/Sao_Paulo')::date))) as pendentes,
          count(*) filter (where status = 'cumprido') as cumpridas,
          count(*) filter (where status = 'cumprido_com_ressalva') as ressalvas,
          count(*) filter (where status = 'atrasado' or (status = 'pendente' and prazo < ((now() at time zone 'America/Sao_Paulo')::date))) as atrasadas,
          count(*) filter (where status = 'validado') as validadas,
          count(*) filter (where status = 'devolvido') as devolvidas,
          count(*) as total
        from tarefas_zona
        """
    )
    row = df.iloc[0].fillna(0)
    total = int(row["total"] or 0)
    conformidade = round((int(row["validadas"] or 0) / total) * 100, 1) if total else 0
    cols = st.columns(7)
    cards = [
        ("Total", total, "#174A7C", "📁"), ("Pendentes", int(row["pendentes"]), "#F59E0B", "⏳"),
        ("Atrasadas", int(row["atrasadas"]), "#B91C1C", "🚨"), ("Cumpridas", int(row["cumpridas"]), "#2563EB", "☑️"),
        ("Validadas", int(row["validadas"]), "#15803D", "✅"), ("Devolvidas", int(row["devolvidas"]), "#C2410C", "↩️"),
        ("% validado", f"{conformidade}%", "#7A60A8", "📈"),
    ]
    for col, (label, value, color, icon) in zip(cols, cards):
        with col:
            render_metric(label, value, color, icon)

    if int(row["atrasadas"] or 0) > 0:
        st_alerta("risco", "Atenção: existem tarefas atrasadas", "Priorize contato orientativo com as Zonas Eleitorais em atraso e registre eventual devolução/validação no sistema.")
    elif total > 0:
        st_alerta("ok", "Nenhum atraso identificado", "Mantenha o acompanhamento preventivo dos prazos e das evidências enviadas.")
    else:
        st_alerta("atenção", "Base ainda sem tarefas", "Faça a carga inicial, importe a planilha e gere o primeiro ciclo de monitoramento.")

    titulo_secao("🧩", "Módulos de fiscalização, gestão e orientação")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(module_card_html("📋", "Plano de ação da planilha", "Veja o checklist original: ELO, Sistemas da Intranet e observações críticas que deram origem ao monitoramento.", "Base inicial do SIMOC"), unsafe_allow_html=True)
        nav_button("Acessar plano", "📌 Plano de ação", "nav_plano_dashboard")
    with m2:
        st.markdown(module_card_html("🗺️", "Zonas eleitorais", "Fiscalize a situação de cada Zona Eleitoral, município-sede, contatos, chefe, juiz e vínculos.", "001ª a 205ª ZE/BA"), unsafe_allow_html=True)
        nav_button("Ver zonas", "🗺️ Zonas eleitorais", "nav_zonas_dashboard")
    with m3:
        st.markdown(module_card_html("✅", "Validação da Corregedoria", "Analise respostas, confira evidências, valide, devolva e registre orientação objetiva para a zona.", "Controle de conformidade"), unsafe_allow_html=True)
        nav_button("Validar respostas", "🔎 Validação", "nav_validacao_dashboard")
    with m4:
        st.markdown(module_card_html("📊", "Relatórios e backup", "Gere PDF, Excel e backup JSON para reuniões, auditoria, acompanhamento e prestação de contas.", "Gestão e memória"), unsafe_allow_html=True)
        nav_button("Gerar relatório", "📄 Relatórios", "nav_relatorios_dashboard")

    titulo_secao("⚡", "Botões de ação imediata")
    b1, b2, b3, b4, b5 = st.columns(5)
    with b1: nav_button("📥 Importar bases", "📥 Importação", "acao_importar")
    with b2: nav_button("⚙️ Gerar tarefas", "⚙️ Gerar tarefas", "acao_tarefas")
    with b3: nav_button("🧭 Orientar zonas", "🧭 Orientações às zonas", "acao_orientar")
    with b4: nav_button("👥 Usuários", "👥 Usuários", "acao_usuarios")
    with b5: nav_button("💾 Backup", "💾 Backup e restauração", "acao_backup")

    with st.expander("📌 Carregar quadros detalhados do painel", expanded=False):
        st.caption("Para o sistema abrir mais rapido, as tabelas detalhadas sao carregadas somente quando voce abre esta area.")
        titulo_secao("🗺️", "Zonas com maior necessidade de acompanhamento")
        zonas = dataframe(
            """
            select lpad(z.numero::text, 3, '0') || 'ª ZE' as zona, z.municipio_sede,
                   count(t.id) filter (where t.status in ('pendente','atrasado','devolvido') or (t.status='pendente' and t.prazo < ((now() at time zone 'America/Sao_Paulo')::date))) as pendencias,
                   count(t.id) filter (where t.status = 'atrasado' or (t.status='pendente' and t.prazo < ((now() at time zone 'America/Sao_Paulo')::date))) as atrasos,
                   count(t.id) as total
            from zonas_eleitorais z
            left join tarefas_zona t on t.zona_eleitoral_id = z.id
            group by z.numero, z.municipio_sede
            order by atrasos desc, pendencias desc, z.numero asc
            limit 30
            """
        )
        st.dataframe(zonas, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            titulo_secao("🎯", "Itens mais pendentes")
            st.dataframe(dataframe("""
                select i.grupo, i.descricao, count(t.id) as pendencias
                from tarefas_zona t join itens_monitoramento i on i.id = t.item_monitoramento_id
                where t.status in ('pendente','atrasado','devolvido') or (t.status='pendente' and t.prazo < ((now() at time zone 'America/Sao_Paulo')::date))
                group by i.grupo, i.descricao order by pendencias desc limit 20
            """), use_container_width=True, hide_index=True)
        with col2:
            titulo_secao("📆", "Evolução por ciclo")
            st.dataframe(dataframe("""
                select c.tipo_periodicidade, c.periodo_inicio, c.periodo_fim,
                       count(t.id) as total,
                       count(t.id) filter (where t.status='validado') as validadas,
                       count(t.id) filter (where t.status='atrasado' or (t.status='pendente' and t.prazo < ((now() at time zone 'America/Sao_Paulo')::date))) as atrasadas
                from ciclos_monitoramento c left join tarefas_zona t on t.ciclo_id=c.id
                group by c.id, c.tipo_periodicidade, c.periodo_inicio, c.periodo_fim
                order by c.periodo_inicio desc limit 12
            """), use_container_width=True, hide_index=True)


def page_zonas():
    st.header("Zonas Eleitorais")
    st.caption("A relação-base usa o padrão 001 a 205 do código anexo; a consulta pública do TRE-BA complementa sede e municípios abrangidos quando importada.")
    filtro = st.text_input("Filtrar por município, zona, e-mail, chefe ou juiz")
    params = {"filtro": f"%{filtro}%"}
    sql = """
        select id, lpad(numero::text,3,'0') as numero, municipio_sede, municipios_abrangidos, email, telefone, chefe_cartorio, juiz_eleitoral, fonte_url, atualizado_em
        from zonas_eleitorais
        where (:filtro='%%' or cast(numero as text) like :filtro or municipio_sede ilike :filtro or coalesce(municipios_abrangidos,'') ilike :filtro or coalesce(email,'') ilike :filtro or coalesce(chefe_cartorio,'') ilike :filtro or coalesce(juiz_eleitoral,'') ilike :filtro)
        order by numero
    """
    st.dataframe(dataframe(sql, **params), use_container_width=True, hide_index=True)


def gerar_ciclo(conn, tipo: str, inicio: date, fim: date) -> int:
    return conn.execute(text("""
        insert into ciclos_monitoramento (periodo_inicio, periodo_fim, tipo_periodicidade, status)
        values (:inicio, :fim, :tipo, 'aberto')
        on conflict (periodo_inicio, periodo_fim, tipo_periodicidade) do update set status = 'aberto'
        returning id
    """), {"inicio": inicio, "fim": fim, "tipo": tipo}).scalar_one()


def page_gerar_tarefas():
    st.header("Interface da Corregedoria: cadastrar e distribuir tarefas")
    st.info("Aqui a Corregedoria transforma os itens do plano de monitoramento em tarefas para as Zonas Eleitorais. As Zonas não criam tarefas; elas apenas executam e preenchem o checklist recebido.")
    titulo_secao("1️⃣", "Definir ciclo, prazo e periodicidade")
    frequencia = st.selectbox("Frequência", ["diaria", "semanal", "quinzenal", "mensal", "bimestral", "trimestral", "anual"])
    inicio = st.date_input("Início", value=date.today().replace(day=1), format="DD/MM/YYYY")
    fim = st.date_input("Fim", value=inicio + timedelta(days=30), format="DD/MM/YYYY")
    prazo = st.date_input("Prazo de preenchimento", value=fim, format="DD/MM/YYYY")
    somente_itens = st.checkbox("Gerar apenas itens ativos desta frequência", value=True)
    titulo_secao("2️⃣", "Enviar tarefas para as Zonas")
    st.caption("O sistema preserva tarefas já criadas para o mesmo ciclo, zona e item. Nada é apagado.")
    if st.button("Gerar tarefas para todas as zonas ativas", type="primary"):
        with db_session() as conn:
            ciclo_id = gerar_ciclo(conn, frequencia, inicio, fim)
            where_item = "and i.frequencia = :freq" if somente_itens else ""
            conn.execute(text(f"""
                insert into tarefas_zona (zona_eleitoral_id, item_monitoramento_id, ciclo_id, prazo, status)
                select z.id, i.id, :ciclo_id, :prazo, 'pendente'
                from zonas_eleitorais z cross join itens_monitoramento i
                where z.ativa = true and i.ativo = true {where_item}
                on conflict (zona_eleitoral_id, item_monitoramento_id, ciclo_id) do nothing
            """), {"ciclo_id": ciclo_id, "prazo": prazo, "freq": frequencia})
        registrar_auditoria("gerar_tarefas", "ciclos_monitoramento", ciclo_id, detalhe=f"{frequencia} {inicio} a {fim}")
        st.success("Tarefas geradas. Se já existiam, foram preservadas.")


def tarefas_df(status_list=None, zona_id=None, limit=500):
    params = {"limit": limit}
    where = ["1=1"]
    if status_list:
        where.append("t.status = any(:status)")
        params["status"] = status_list
    if zona_id:
        where.append("t.zona_eleitoral_id = :zona_id")
        params["zona_id"] = zona_id
    return dataframe(f"""
        select t.id, lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.municipio_sede, i.grupo, i.descricao, i.frequencia, i.criticidade,
               t.prazo, t.status, c.periodo_inicio, c.periodo_fim
        from tarefas_zona t
        join zonas_eleitorais z on z.id = t.zona_eleitoral_id
        join itens_monitoramento i on i.id = t.item_monitoramento_id
        join ciclos_monitoramento c on c.id = t.ciclo_id
        where {' and '.join(where)}
        order by t.prazo asc, z.numero asc, i.grupo asc
        limit :limit
    """, **params)


def page_minhas_tarefas():
    st.markdown("""
    <div class='interface-banner zona'>
        <h2>🏛️ Interface da Zona Eleitoral</h2>
        <p><b>Função da Zona:</b> executar as tarefas recebidas da Corregedoria e preencher o checklist com status, observação e evidência.</p>
        <p>A Zona não cadastra tarefas gerais, não gera ciclo e não valida respostas. A resposta enviada fica disponível para análise da Corregedoria.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='step-flow'><span>1. Ver tarefa</span><span>2. Executar rotina</span><span>3. Marcar checklist</span><span>4. Informar evidência</span><span>5. Enviar à Corregedoria</span></div>", unsafe_allow_html=True)

    user = usuario_logado()
    zona_id = user.get("zona_eleitoral_id") if perfil_atual() in ["chefe_cartorio", "substituto"] else None
    if eh_zona() and not zona_id:
        st.error("Seu usuário está como perfil de Zona, mas não possui Zona Eleitoral vinculada. Peça à Corregedoria para vincular seu cadastro à zona correta.")
        return

    colf1, colf2 = st.columns([2, 1])
    with colf1:
        filtro_status = st.multiselect("Filtrar checklist por status", STATUS_TAREFA, default=["pendente", "atrasado", "devolvido"])
    with colf2:
        limite = st.number_input("Quantidade máxima", min_value=20, max_value=500, value=100, step=20)

    tarefas = tarefas_df(filtro_status, zona_id, int(limite))
    st.dataframe(tarefas, use_container_width=True, hide_index=True)
    if tarefas.empty:
        st.success("Nenhuma tarefa encontrada para o filtro selecionado.")
        return

    st.subheader("Preencher checklist da tarefa")
    tarefa_id = st.selectbox("Escolha a tarefa para preencher", tarefas["id"].tolist())
    tarefa_sel = tarefas[tarefas["id"] == tarefa_id].iloc[0].to_dict()
    st.markdown(
        f"""
        <div class='guide-box'>
            <h4>{tarefa_sel.get('grupo','')} · {tarefa_sel.get('zona','')}</h4>
            <p><b>Tarefa:</b> {tarefa_sel.get('descricao','')}</p>
            <p><b>Prazo:</b> {tarefa_sel.get('prazo','')} · <b>Status atual:</b> {tarefa_sel.get('status','')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Histórico da tarefa", expanded=False):
        hist = dataframe("""
            select r.enviado_em as data, u.nome as usuario, r.status, r.observacao, r.justificativa, r.evidencia_url
            from respostas r join usuarios u on u.id=r.usuario_id where r.tarefa_zona_id=:id order by r.enviado_em desc
        """, id=tarefa_id)
        st.dataframe(hist, use_container_width=True, hide_index=True)
        comentarios = dataframe("select criado_em, autor_nome, comentario from comentarios_tarefa where tarefa_zona_id=:id order by criado_em desc", id=tarefa_id)
        st.dataframe(comentarios, use_container_width=True, hide_index=True)

    with st.form("responder_checklist_zona"):
        status = st.radio("Marcar checklist", ["cumprido", "cumprido_com_ressalva", "nao_se_aplica", "pendente"], horizontal=True)
        observacao = st.text_area("Observação da Zona", placeholder="Informe o que foi realizado, data da conferência ou situação encontrada.")
        justificativa = st.text_area("Justificativa, se houver", placeholder="Use quando houver ressalva, impedimento, pendência ou não aplicação.")
        evidencia_url = st.text_input("Link da evidência / documento SEI / comprovante")
        anexo_nome = st.text_input("Nome do anexo ou evidência")
        anexo_url = st.text_input("URL complementar do anexo, se houver")
        submitted = st.form_submit_button("Enviar checklist para a Corregedoria", type="primary")

    if submitted:
        with db_session() as conn:
            conn.execute(text("""
                insert into respostas (tarefa_zona_id, usuario_id, status, observacao, justificativa, evidencia_url)
                values (:tarefa, :usuario, :status, :observacao, :justificativa, :evidencia)
            """), {"tarefa": tarefa_id, "usuario": user["id"], "status": status, "observacao": observacao, "justificativa": justificativa, "evidencia": evidencia_url})
            novo_status = "em_analise" if status in ["cumprido", "cumprido_com_ressalva", "nao_se_aplica"] else status
            conn.execute(text("update tarefas_zona set status=:status, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"status": novo_status, "id": tarefa_id})
            if anexo_url.strip():
                conn.execute(text("""
                    insert into anexos_tarefa (tarefa_zona_id, nome_arquivo, url_arquivo, enviado_por_usuario_id, enviado_por_nome, enviado_por_email)
                    values (:id, :nome_arq, :url, :uid, :nome, :email)
                """), {"id": tarefa_id, "nome_arq": anexo_nome or "Link de evidência", "url": anexo_url, "uid": user["id"], "nome": user["nome"], "email": user["email"]})
        registrar_auditoria("zona_envia_checklist", "tarefas_zona", tarefa_id, campo="status", novo=status)
        st.success("Checklist enviado para análise da Corregedoria.")
        st.rerun()


def page_validacao():
    st.header("Validação da Corregedoria")
    respostas = dataframe("""
        select distinct on (r.tarefa_zona_id)
               r.id as resposta_id, t.id as tarefa_id, lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.municipio_sede,
               i.grupo, i.descricao, r.status, r.observacao, r.justificativa, r.evidencia_url, r.enviado_em
        from respostas r
        join tarefas_zona t on t.id = r.tarefa_zona_id
        join zonas_eleitorais z on z.id = t.zona_eleitoral_id
        join itens_monitoramento i on i.id = t.item_monitoramento_id
        where t.status in ('cumprido','cumprido_com_ressalva','nao_se_aplica','em_analise')
        order by r.tarefa_zona_id, r.enviado_em desc
        limit 300
    """)
    st.dataframe(respostas, use_container_width=True, hide_index=True)
    if respostas.empty:
        return
    resposta_id = st.selectbox("Resposta", respostas["resposta_id"].tolist())
    acao = st.selectbox("Validação", ["validado", "devolvido", "em_analise"])
    obs = st.text_area("Observação da Corregedoria")
    if st.button("Registrar validação", type="primary"):
        user = usuario_logado()
        tarefa_id = int(respostas.loc[respostas["resposta_id"] == resposta_id, "tarefa_id"].iloc[0])
        with db_session() as conn:
            conn.execute(text("""
                insert into validacoes_corregedoria (resposta_id, usuario_corregedoria_id, status_validacao, observacao)
                values (:resposta, :usuario, :status, :obs)
            """), {"resposta": int(resposta_id), "usuario": user["id"], "status": acao, "obs": obs})
            conn.execute(text("update tarefas_zona set status=:status, observacao_corregedoria=:obs, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"status": acao, "obs": obs, "id": tarefa_id})
        registrar_auditoria("validar_check", "tarefas_zona", tarefa_id, campo="status", novo=acao, detalhe=obs)
        st.success("Validação registrada.")
        st.rerun()


# ============================================================
# IMPORTAÇÃO, USUÁRIOS, BACKUP E RELATÓRIOS
# ============================================================


def page_importacao():
    st.header("Carga inicial e importações")
    st.info("Regra corrigida: ao abrir o sistema, nenhuma zona, município, planilha ou tarefa é carregada automaticamente. As ações abaixo só rodam quando o administrador clicar no botão.")
    resumo = dataframe("""
        select (select count(*) from zonas_eleitorais) as zonas,
               (select count(*) from municipios_zona) as municipios_vinculados,
               (select count(*) from itens_monitoramento) as itens,
               (select count(*) from tarefas_zona) as tarefas
    """)
    if not resumo.empty:
        z = int(resumo.iloc[0]["zonas"] or 0)
        m = int(resumo.iloc[0]["municipios_vinculados"] or 0)
        i = int(resumo.iloc[0]["itens"] or 0)
        t = int(resumo.iloc[0]["tarefas"] or 0)
        st.caption(f"Base atual no Supabase: {z} zonas, {m} municípios vinculados, {i} itens da planilha e {t} tarefas. Se essa base já estiver correta, não clique nos botões de importação.")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Criar/atualizar schema"):
        run_schema(); limpar_cache_dados(); st.session_state.bootstrap_ok = True; st.success("Schema verificado/criado no Supabase.")
    if c2.button("Importar consulta pública TRE-BA"):
        with db_session() as conn:
            base = seed_zonas_bahia_padrao(conn)
            total = importar_zonas(conn)
        limpar_cache_dados()
        registrar_auditoria("importar_zonas", "zonas_eleitorais", detalhe=TREBA_CONSULTA_CARTORIOS_URL)
        st.success(f"Relação-base garantida ({base} zonas) e {total} zonas atualizadas pela consulta pública: {TREBA_CONSULTA_CARTORIOS_URL}")
    if c3.button("Garantir zonas 001-205"):
        with db_session() as conn:
            total = seed_zonas_bahia_padrao(conn)
        limpar_cache_dados()
        st.success(f"{total} zonas da relação-base 001 a 205 foram verificadas.")
    if c4.button("Importar planilha padrão"):
        ods = Path(__file__).parent / "PLANO DE AÇÃO - MONITORAMENTO CARTORÁRIO.ods"
        with db_session() as conn:
            total = importar_itens_ods(conn, ods)
        limpar_cache_dados()
        registrar_auditoria("importar_planilha", "itens_monitoramento", detalhe=str(ods))
        st.success(f"{total} itens de monitoramento processados a partir da planilha.")

    uploaded = st.file_uploader("Importar outra planilha ODS", type=["ods"])
    if uploaded and st.button("Importar arquivo enviado"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ods") as tmp:
            tmp.write(uploaded.getbuffer()); tmp_path = tmp.name
        with db_session() as conn:
            total = importar_itens_ods(conn, tmp_path)
        os.unlink(tmp_path)
        limpar_cache_dados()
        st.success(f"{total} itens processados.")

    st.subheader("Resumo da base")
    st.dataframe(dataframe("""
        select (select count(*) from zonas_eleitorais) as zonas,
               (select count(*) from municipios_zona) as municipios_vinculados,
               (select count(*) from itens_monitoramento) as itens,
               (select count(*) from usuarios) as usuarios,
               (select count(*) from tarefas_zona) as tarefas
    """), hide_index=True, use_container_width=True)


def page_usuarios():
    st.header("Usuários e permissões")
    perfis = dataframe("select id, nome, descricao from perfis order by nome")
    abas = st.tabs(["Cadastrar/atualizar", "Usuários ativos", "Validação e recuperação"])
    with abas[0]:
        with st.form("novo_usuario"):
            nome = st.text_input("Nome")
            email = normalizar_email(st.text_input("E-mail"))
            cpf = st.text_input("CPF, opcional")
            perfil_nome = st.selectbox("Perfil", perfis["nome"].tolist())
            zona_label = st.selectbox("Zona vinculada", zonas_options())
            senha = st.text_input("Senha inicial / nova senha", type="password")
            ativo = st.checkbox("Ativo", value=True)
            validado = st.checkbox("Validado", value=True)
            submitted = st.form_submit_button("Salvar usuário", type="primary")
        if submitted:
            if not nome.strip() or not email:
                st.warning("Informe nome e e-mail.")
            elif len(senha or "") < 6:
                st.warning("Informe senha com pelo menos 6 caracteres.")
            else:
                perfil_id = int(perfis.loc[perfis["nome"] == perfil_nome, "id"].iloc[0])
                zona_id = zona_id_from_label(zona_label)
                with db_session() as conn:
                    conn.execute(text("""
                        insert into usuarios (nome, email, cpf, senha_hash, perfil_id, zona_eleitoral_id, ativo, validado, secao_operador, atualizado_em)
                        values (:nome, :email, :cpf, :senha, :perfil, :zona, :ativo, :validado, :secao, (now() at time zone 'America/Sao_Paulo'))
                        on conflict (email) do update set nome=excluded.nome, cpf=excluded.cpf, senha_hash=excluded.senha_hash, perfil_id=excluded.perfil_id, zona_eleitoral_id=excluded.zona_eleitoral_id, ativo=excluded.ativo, validado=excluded.validado, atualizado_em=(now() at time zone 'America/Sao_Paulo')
                    """), {"nome": nome, "email": email, "cpf": cpf or None, "senha": hash_password(str(senha)[:72]), "perfil": perfil_id, "zona": zona_id, "ativo": ativo, "validado": validado, "secao": UNIDADE_CORREGEDORIA})
                registrar_auditoria("salvar_usuario", "usuarios", detalhe=email)
                st.success("Usuário criado/atualizado.")
    with abas[1]:
        st.dataframe(dataframe("""
            select u.id, u.nome, u.email, p.nome as perfil, lpad(z.numero::text,3,'0') as zona, z.municipio_sede, u.ativo, u.validado, u.ultimo_login, u.atualizado_em
            from usuarios u join perfis p on p.id = u.perfil_id left join zonas_eleitorais z on z.id = u.zona_eleitoral_id order by u.nome
        """), use_container_width=True, hide_index=True)
    with abas[2]:
        usuarios_df = dataframe("select id, nome, email, ativo, validado from usuarios order by nome")
        st.dataframe(usuarios_df, use_container_width=True, hide_index=True)
        if not usuarios_df.empty:
            uid = st.selectbox("Selecionar usuário", usuarios_df["id"].tolist())
            col1, col2, col3 = st.columns(3)
            if col1.button("Validar cadastro"):
                execute("update usuarios set validado=true, ativo=true, token_validacao=null, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id", id=int(uid))
                registrar_auditoria("validar_usuario_admin", "usuarios", int(uid)); st.success("Usuário validado.")
            if col2.button("Desativar/ativar"):
                execute("update usuarios set ativo=not ativo, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id", id=int(uid))
                registrar_auditoria("alternar_ativo_usuario", "usuarios", int(uid)); st.success("Situação alterada.")
            if col3.button("Gerar token de recuperação"):
                token = secrets.token_urlsafe(32); expira = agora_brasilia()+timedelta(hours=2)
                execute("update usuarios set token_recuperacao=:token, token_recuperacao_expira_em=:expira where id=:id", token=token, expira=expira.replace(tzinfo=None), id=int(uid))
                st.info(f"Link: {gerar_link_recuperacao(token)}")


def montar_backup_completo() -> dict:
    tabelas = ["perfis", "zonas_eleitorais", "municipios_zona", "usuarios", "itens_monitoramento", "ciclos_monitoramento", "tarefas_zona", "respostas", "validacoes_corregedoria", "comentarios_tarefa", "anexos_tarefa", "logs_auditoria"]
    backup = {"sistema": NOME_SISTEMA, "gerado_em": agora_iso(), "versao": "streamlit-supabase-full", "tabelas": {}}
    with db_session() as conn:
        for t in tabelas:
            rows = conn.execute(text(f"select * from {t}")).mappings().all()
            backup["tabelas"][t] = [dict(r) for r in rows]
    return backup


def backup_to_json_bytes(backup: dict) -> bytes:
    return json.dumps(backup, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def registrar_backup(nome: str, tipo: str, data: bytes, qtd: int):
    h = hashlib.sha256(data).hexdigest()
    u = usuario_logado()
    with db_session() as conn:
        conn.execute(text("""
            insert into backups_registros (nome_arquivo, tipo, quantidade_registros, gerado_por_usuario_id, gerado_por_nome, gerado_por_email, hash_sha256)
            values (:nome, :tipo, :qtd, :uid, :unome, :email, :hash)
        """), {"nome": nome, "tipo": tipo, "qtd": qtd, "uid": u.get("id"), "unome": u.get("nome"), "email": u.get("email"), "hash": h})
    return h


def page_backup():
    st.header("Backup e restauração")
    st.warning("Em Streamlit Cloud, não dependa de arquivos internos do app. Baixe backups JSON/Excel e mantenha a base principal no Supabase.")
    backup = montar_backup_completo()
    json_bytes = backup_to_json_bytes(backup)
    qtd = sum(len(v) for v in backup["tabelas"].values())
    nome_json = f"backup_simoc_ba_{agora_brasilia().strftime('%Y%m%d_%H%M%S')}.json"
    if st.download_button("Baixar backup completo em JSON", data=json_bytes, file_name=nome_json, mime="application/json", type="primary"):
        registrar_backup(nome_json, "json", json_bytes, qtd)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for tabela, rows in backup["tabelas"].items():
            df = pd.DataFrame(rows)
            if tabela == "usuarios" and not df.empty:
                df = df.drop(columns=[c for c in ["senha_hash", "token_validacao", "token_recuperacao"] if c in df.columns], errors="ignore")
            df.to_excel(writer, index=False, sheet_name=tabela[:31])
    nome_xlsx = f"copia_conferencia_simoc_ba_{agora_brasilia().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if st.download_button("Baixar cópia em Excel para conferência", data=buffer.getvalue(), file_name=nome_xlsx, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        registrar_backup(nome_xlsx, "excel", buffer.getvalue(), qtd)

    st.divider()
    st.subheader("Restaurar backup JSON")
    st.info("A restauração substitui dados operacionais. Use somente por administrador e com confirmação expressa.")
    arquivo = st.file_uploader("Arquivo JSON de backup", type=["json"])
    if arquivo is not None:
        dados = json.loads(arquivo.read().decode("utf-8"))
        st.write({t: len(rows) for t, rows in dados.get("tabelas", {}).items()})
        confirmar = st.checkbox("Confirmo que desejo restaurar este backup e substituir os dados atuais.")
        if st.button("Restaurar backup", type="primary"):
            if not confirmar:
                st.warning("Marque a confirmação antes de restaurar.")
            else:
                tabelas_ordem = ["validacoes_corregedoria", "respostas", "comentarios_tarefa", "anexos_tarefa", "tarefas_zona", "ciclos_monitoramento", "itens_monitoramento", "municipios_zona", "usuarios", "zonas_eleitorais", "perfis"]
                tabelas_insert = list(reversed(tabelas_ordem))
                with db_session() as conn:
                    for t in tabelas_ordem:
                        if t in dados.get("tabelas", {}):
                            conn.execute(text(f"delete from {t}"))
                    for t in tabelas_insert:
                        rows = dados.get("tabelas", {}).get(t, [])
                        for row in rows:
                            if not row:
                                continue
                            cols = list(row.keys())
                            placeholders = [f":{c}" for c in cols]
                            conn.execute(text(f"insert into {t} ({', '.join(cols)}) values ({', '.join(placeholders)}) on conflict do nothing"), row)
                registrar_auditoria("restaurar_backup", "sistema", detalhe=arquivo.name)
                st.success("Backup restaurado. Atualize o aplicativo.")
                st.rerun()
    st.divider()
    st.subheader("Histórico de backups gerados")
    st.dataframe(dataframe("select nome_arquivo, tipo, quantidade_registros, gerado_por_nome, hash_sha256, criado_em from backups_registros order by criado_em desc limit 100"), use_container_width=True, hide_index=True)


def relatorio_base_df(status=None, zona_id=None, data_de=None, data_ate=None):
    where = ["1=1"]
    params = {}
    if status:
        where.append("t.status = any(:status)"); params["status"] = status
    if zona_id:
        where.append("z.id=:zona_id"); params["zona_id"] = zona_id
    if data_de:
        where.append("t.prazo >= :data_de"); params["data_de"] = data_de
    if data_ate:
        where.append("t.prazo <= :data_ate"); params["data_ate"] = data_ate
    return dataframe(f"""
        select t.id as "ID", lpad(z.numero::text,3,'0') || 'ª ZE' as "Zona", z.municipio_sede as "Município-sede",
               i.grupo as "Grupo", i.descricao as "Item", i.frequencia as "Frequência", i.criticidade as "Criticidade",
               c.periodo_inicio as "Início ciclo", c.periodo_fim as "Fim ciclo", t.prazo as "Prazo", t.status as "Status",
               r.enviado_em as "Último envio", u.nome as "Último usuário", r.observacao as "Observação", r.justificativa as "Justificativa",
               v.status_validacao as "Validação", v.observacao as "Obs. Corregedoria"
        from tarefas_zona t
        join zonas_eleitorais z on z.id=t.zona_eleitoral_id
        join itens_monitoramento i on i.id=t.item_monitoramento_id
        join ciclos_monitoramento c on c.id=t.ciclo_id
        left join lateral (select * from respostas r where r.tarefa_zona_id=t.id order by r.enviado_em desc limit 1) r on true
        left join usuarios u on u.id=r.usuario_id
        left join lateral (select * from validacoes_corregedoria v where v.resposta_id=r.id order by v.validado_em desc limit 1) v on true
        where {' and '.join(where)}
        order by t.prazo desc, z.numero asc, i.grupo asc
    """, **params)


def tabela_pdf(df: pd.DataFrame, limite=90):
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle
    cols = [c for c in ["ID", "Zona", "Município-sede", "Grupo", "Item", "Prazo", "Status", "Validação"] if c in df.columns]
    temp = df[cols].head(limite).fillna("").astype(str)
    dados = [cols] + temp.values.tolist() if not temp.empty else [["Mensagem"], ["Não há registros para os filtros aplicados."]]
    tabela = Table(dados, repeatRows=1, colWidths=[1.2*cm, 2*cm, 3.2*cm, 2.4*cm, 7.5*cm, 2*cm, 2.7*cm, 2.7*cm][:len(dados[0])])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#174A7C")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 6.5),
        ("GRID", (0,0), (-1,-1), 0.2, colors.HexColor("#D9E2EF")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    return tabela


def gerar_relatorio_pdf(df: pd.DataFrame, filtros: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1.1*cm, leftMargin=1.1*cm, topMargin=1.2*cm, bottomMargin=1.2*cm, title="Relatório SIMOC-BA")
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=16, alignment=TA_CENTER, textColor=colors.HexColor("#174A7C"))
    h2 = ParagraphStyle("H2", parent=estilos["Heading2"], fontSize=11, textColor=colors.HexColor("#174A7C"))
    normal = ParagraphStyle("Normal", parent=estilos["Normal"], fontSize=8.5, leading=11)
    elementos = [Paragraph("RELATÓRIO GERENCIAL DE MONITORAMENTO CARTORÁRIO - SIMOC-BA", titulo), Paragraph("Corregedoria Regional Eleitoral da Bahia", normal), Spacer(1, .3*cm)]
    elementos.append(Paragraph("1. Identificação e filtros", h2))
    usuario = usuario_logado()
    elementos.append(Paragraph(f"<b>Usuário emissor:</b> {usuario.get('nome','')} ({usuario.get('email','')})", normal))
    elementos.append(Paragraph(f"<b>Emissão:</b> {agora_texto()} - Horário de Brasília", normal))
    elementos.append(Paragraph("<b>Filtros:</b> " + json.dumps(filtros, ensure_ascii=False, default=str), normal))
    elementos.append(Spacer(1, .25*cm))
    elementos.append(Paragraph("2. Resumo executivo", h2))
    total = len(df)
    resumo = pd.DataFrame([{"Indicador": "Total filtrado", "Quantidade": total}] + [{"Indicador": f"Status: {k}", "Quantidade": int(v)} for k, v in df["Status"].value_counts().items()] if not df.empty else [{"Indicador":"Total filtrado","Quantidade":0}])
    elementos.append(tabela_pdf(resumo.rename(columns={"Indicador":"Item", "Quantidade":"Status"}), limite=20))
    elementos.append(Spacer(1, .25*cm))
    elementos.append(Paragraph("3. Tabela analítica", h2))
    elementos.append(Paragraph("São exibidos até 90 registros para preservar a legibilidade do PDF. A exportação Excel contém a base completa filtrada.", normal))
    elementos.append(tabela_pdf(df, limite=90))
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


def page_relatorios():
    st.header("Relatórios e exportação")
    col1, col2, col3 = st.columns(3)
    with col1:
        status = st.multiselect("Status", STATUS_TAREFA)
    with col2:
        zona_label = st.selectbox("Zona", zonas_options())
        zona_id = zona_id_from_label(zona_label)
    with col3:
        data_de = st.date_input("Prazo de", value=None, format="DD/MM/YYYY")
        data_ate = st.date_input("Prazo até", value=None, format="DD/MM/YYYY")
    df = relatorio_base_df(status or None, zona_id, data_de, data_ate)
    st.caption(f"Registros encontrados: {len(df)}")
    st.dataframe(df, use_container_width=True, hide_index=True)
    filtros = {"status": status, "zona": zona_label, "data_de": data_de, "data_ate": data_ate, "emissao": agora_texto()}
    pdf = gerar_relatorio_pdf(df, filtros)
    st.download_button("Gerar relatório PDF apresentável", data=pdf, file_name=f"relatorio_simoc_ba_{agora_brasilia().strftime('%Y%m%d_%H%M')}.pdf", mime="application/pdf", type="primary")
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Base filtrada")
        if not df.empty:
            df["Status"].value_counts().rename_axis("Status").reset_index(name="Quantidade").to_excel(writer, index=False, sheet_name="Por status")
            df["Zona"].value_counts().rename_axis("Zona").reset_index(name="Quantidade").to_excel(writer, index=False, sheet_name="Por zona")
            df["Grupo"].value_counts().rename_axis("Grupo").reset_index(name="Quantidade").to_excel(writer, index=False, sheet_name="Por grupo")
    st.download_button("Exportar Excel completo", data=buffer.getvalue(), file_name=f"relatorio_simoc_ba_{agora_brasilia().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")



def page_plano_acao():
    st.header("📌 Plano de ação da planilha inicial")
    st.caption("Esta página mantém viva a origem do sistema: transformar cada item da planilha de monitoramento em tarefa fiscalizável, com prazo, responsável, evidência, validação e orientação.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(module_card_html("🧾", "ELO", "Rotinas eleitorais que exigem conferência recorrente, evidência e registro de cumprimento pela Zona Eleitoral.", "RAE, multa, ASE, lotes"), unsafe_allow_html=True)
    with c2:
        st.markdown(module_card_html("🖥️", "Sistemas da Intranet", "Acompanhamento de sistemas administrativos, judiciais e operacionais usados pelos cartórios eleitorais.", "PJe, DJE, SEI, ATENA"), unsafe_allow_html=True)
    with c3:
        st.markdown(module_card_html("🧭", "Observações críticas", "Determinações operacionais que precisam ser acompanhadas até o saneamento completo.", "PJe, livros e processos"), unsafe_allow_html=True)

    titulo_secao("🧾", "Itens ELO da planilha")
    planilha_chips([
        "RAE em diligência", "Pagamento de multa eleitoral", "Perda/suspensão", "Banco de Erros", "Duplicidade/Coincidência",
        "Lote de RAE em processamento", "Multa + ASE", "Atualização do logradouro", "Requerimento Web", "Edital de Lotes de RAEs", "Lotes assinados no SEI"
    ])
    st.markdown("<div class='orientation-strip'><b>Uso no sistema:</b> cada item vira tarefa com periodicidade, prazo, status, justificativa e evidência. A Corregedoria valida ou devolve com orientação.</div>", unsafe_allow_html=True)

    titulo_secao("🖥️", "Sistemas da Intranet da planilha")
    planilha_chips([
        "Agenda eletrônica", "ASIWEB", "INFODIP", "JUSTIFICA", "LOGUSWEB", "PJe", "DJE", "ATENA", "Reembolsa", "INFOJUD", "BACENJUD", "RENAJUD", "SICO", "Mesário Voluntário", "SEI", "SAPF"
    ])
    st.markdown("<div class='orientation-strip'><b>Uso no sistema:</b> os itens por demanda não somem; eles podem ser gerados como tarefas específicas quando a Corregedoria precisar fiscalizar ou orientar determinada zona.</div>", unsafe_allow_html=True)

    titulo_secao("🚨", "Observações que merecem alerta")
    st.markdown("""
    <div class='risk-strip'><b>PJe:</b> acompanhar atualização de documentos e saneamento de processos, exceto os sobrestados.</div>
    <div class='risk-strip'><b>SEI:</b> verificar abertura e manutenção dos livros obrigatórios eletrônicos.</div>
    <div class='risk-strip'><b>Processos pendentes:</b> permitir que a Corregedoria registre orientação, prazo de regularização e validação posterior.</div>
    """, unsafe_allow_html=True)

    titulo_secao("🎯", "Como fiscalizar cada item")
    w1, w2, w3, w4 = st.columns(4)
    with w1: workflow_card("1️⃣", "Gerar tarefa", "A Corregedoria seleciona frequência e período, e o sistema cria tarefas por Zona Eleitoral.")
    with w2: workflow_card("2️⃣", "Zona responde", "Chefe/Substituto informa status, justificativa e evidência ou link do documento.")
    with w3: workflow_card("3️⃣", "Corregedoria valida", "A resposta é validada, devolvida ou colocada em análise com orientação objetiva.")
    with w4: workflow_card("4️⃣", "Relatório e auditoria", "O resultado fica registrado em dashboard, relatório PDF/Excel, backup e trilha de auditoria.")

    cta1, cta2, cta3 = st.columns(3)
    with cta1: nav_button("⚙️ Gerar tarefas da planilha", "⚙️ Gerar tarefas", "plano_gerar")
    with cta2: nav_button("✅ Preencher checklist", "✅ Minhas tarefas", "plano_check")
    with cta3: nav_button("📄 Relatório de cumprimento", "📄 Relatórios", "plano_relatorio")

def page_orientacoes():
    st.header("🧭 Orientações às Zonas Eleitorais")
    st.caption("Área para orientar, padronizar comunicação e reduzir reincidência de pendências nas Zonas Eleitorais.")

    o1, o2, o3, o4 = st.columns(4)
    with o1:
        st.markdown(module_card_html("⏰", "Antes do prazo", "Lembre a zona sobre o item, prazo, periodicidade e evidência esperada.", "Orientação preventiva"), unsafe_allow_html=True)
    with o2:
        st.markdown(module_card_html("🚨", "Pendência/atraso", "Contato orientativo, registro da justificativa e prazo de regularização.", "Acompanhamento ativo"), unsafe_allow_html=True)
    with o3:
        st.markdown(module_card_html("🔁", "Devolução", "Explique objetivamente o que faltou e qual evidência deve ser complementada.", "Correção assistida"), unsafe_allow_html=True)
    with o4:
        st.markdown(module_card_html("✅", "Validação", "Registre conformidade, preserve histórico e permita relatório gerencial.", "Encerramento do ciclo"), unsafe_allow_html=True)

    titulo_secao("🧾", "Roteiro orientativo baseado na planilha inicial")
    st.markdown("""
    <div class='guide-box'><h4>ELO</h4><p>Verifique RAE em diligência, multa, perda/suspensão, banco de erros, duplicidade/coincidência, lote RAE, requerimento web, edital de RAEs e inserção no SEI.</p></div>
    <div class='guide-box'><h4>Sistemas da Intranet</h4><p>Confira Agenda, ASIWEB, INFODIP, JUSTIFICA, LOGUSWEB, PJe, DJE, ATENA, Reembolsa, INFOJUD, BACENJUD, RENAJUD, SICO, Mesário Voluntário, SEI e SAPF.</p></div>
    <div class='guide-box'><h4>Observações críticas</h4><p>Priorize atualização de documentos no PJe, abertura dos livros obrigatórios no SEI e saneamento dos processos pendentes.</p></div>
    """, unsafe_allow_html=True)

    titulo_secao("🛠️", "Botões para atuação da Corregedoria")
    b1, b2, b3, b4 = st.columns(4)
    with b1: nav_button("🔎 Validar respostas", "🔎 Validação", "orient_validar")
    with b2: nav_button("📊 Ver painel", "📊 Painel de fiscalização", "orient_painel")
    with b3: nav_button("📄 Emitir relatório", "📄 Relatórios", "orient_relatorio")
    with b4: nav_button("🗺️ Consultar zona", "🗺️ Zonas eleitorais", "orient_zona")

    titulo_secao("✉️", "Modelos de orientação")
    tab1, tab2, tab3 = st.tabs(["Pendência", "Devolução", "Validação"])
    with tab1:
        st.text_area("Mensagem de pendência", value=(
            "Prezada(o) Chefe de Cartório,\n\n"
            "Consta no SIMOC-BA pendência referente a item do plano de monitoramento cartorário. "
            "Solicitamos verificar a atividade, registrar o status no sistema e informar a evidência correspondente.\n\n"
            "Caso haja impedimento, favor registrar justificativa objetiva para análise da Corregedoria.\n\n"
            "Atenciosamente,\nCorregedoria Regional Eleitoral da Bahia"
        ), height=190)
    with tab2:
        st.text_area("Mensagem de devolução", value=(
            "Prezada(o) Chefe de Cartório,\n\n"
            "A resposta enviada no SIMOC-BA foi devolvida para complementação. "
            "Favor revisar a orientação registrada pela Corregedoria, complementar a evidência e reenviar o item para nova análise.\n\n"
            "Atenciosamente,\nCorregedoria Regional Eleitoral da Bahia"
        ), height=190)
    with tab3:
        st.text_area("Mensagem de validação", value=(
            "Prezada(o) Chefe de Cartório,\n\n"
            "A Corregedoria validou o item de monitoramento no SIMOC-BA. O registro ficará preservado para histórico, relatório e auditoria.\n\n"
            "Agradecemos a colaboração.\n\n"
            "Atenciosamente,\nCorregedoria Regional Eleitoral da Bahia"
        ), height=190)

def page_auditoria():
    st.header("Auditoria e histórico")
    st.dataframe(dataframe("select criado_em, usuario_nome, usuario_email, acao, entidade, entidade_id, campo, valor_anterior, valor_novo, detalhe from logs_auditoria order by criado_em desc limit 500"), use_container_width=True, hide_index=True)


def main():
    # Para abrir rapido, a tela inicial nao conecta ao Supabase.
    # O banco so e acessado apos o clique em Entrar/Cadastrar/Recuperar.
    if "user" not in st.session_state:
        login_box()
        return
    if not garantir_banco_para_acao():
        return
    cabecalho()
    sidebar_user()
    perfil = perfil_atual()

    if eh_zona():
        pages = ["🏠 Início da Zona", "✅ Checklist da Zona", "📌 Plano de ação", "🧭 Orientações"]
    elif eh_corregedoria():
        pages = ["🏠 Início da Corregedoria", "📊 Painel da Corregedoria", "📌 Plano de ação", "⚙️ Cadastrar tarefas", "🔎 Validar checklist", "🗺️ Zonas eleitorais", "🧭 Orientações às Zonas", "📄 Relatórios"]
        if perfil == "admin":
            pages += ["📥 Importação", "👥 Usuários", "💾 Backup e restauração", "🧾 Auditoria"]
    elif perfil == "auditor":
        pages = ["📊 Painel da Corregedoria", "📄 Relatórios", "🗺️ Zonas eleitorais"]
    else:
        pages = ["📌 Plano de ação"]

    target = st.session_state.pop("nav_target", None)
    index = pages.index(target) if target in pages else 0
    page = st.sidebar.radio("Navegação", pages, index=index)

    if page == "🏠 Início da Corregedoria": page_inicio_corregedoria()
    elif page == "🏠 Início da Zona": page_inicio_zona()
    elif page == "📊 Painel da Corregedoria": page_dashboard()
    elif page == "📌 Plano de ação": page_plano_acao()
    elif page == "🗺️ Zonas eleitorais": page_zonas()
    elif page == "✅ Checklist da Zona": page_minhas_tarefas()
    elif page == "🧭 Orientações": page_orientacoes()
    elif page == "🧭 Orientações às Zonas": page_orientacoes()
    elif page == "🔎 Validar checklist": page_validacao()
    elif page == "⚙️ Cadastrar tarefas": page_gerar_tarefas()
    elif page == "📥 Importação": page_importacao()
    elif page == "👥 Usuários": page_usuarios()
    elif page == "💾 Backup e restauração": page_backup()
    elif page == "📄 Relatórios": page_relatorios()
    elif page == "🧾 Auditoria": page_auditoria()


if __name__ == "__main__":
    main()
