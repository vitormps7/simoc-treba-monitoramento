from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import base64
import hashlib
import json
import os
import secrets
import smtplib
from email.message import EmailMessage

import pandas as pd
import streamlit as st
from sqlalchemy import text

from db import db_session, run_schema
from security import hash_password, verify_password
from logo_corregedoria import LOGO_CORREGEDORIA_BASE64
from treba_importer import importar_zonas, seed_zonas_bahia_padrao, TREBA_CONSULTA_CARTORIOS_URL

st.set_page_config(page_title="SIMOC-BA", page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed")

# ============================================================
# CONFIGURAÇÕES GERAIS
# ============================================================

FUSO_HORARIO_BRASILIA = timezone(timedelta(hours=-3), name="BRT")
FORMATO_DATA = "%d/%m/%Y"
FORMATO_DATA_HORA = "%d/%m/%Y %H:%M"
NOME_SISTEMA = "SIMOC-BA"
NOME_COMPLETO = "Sistema de Monitoramento Cartorário das Zonas Eleitorais da Bahia"
DOMINIO_INSTITUCIONAL = "@tre-ba.jus.br"
UNIDADE_CORREGEDORIA = "CRE-BA"
APP_BASE_URL_DEFAULT = ""

PERFIS = [
    ("admin", "Administrador do sistema"),
    ("corregedoria_gestor", "Corregedoria - gestor"),
    ("corregedoria_analista", "Corregedoria - analista"),
    ("chefe_cartorio", "Zona Eleitoral - chefe de cartório"),
    ("substituto", "Zona Eleitoral - substituto"),
    ("auditor", "Auditoria/consulta"),
]
PERFIS_CORREGEDORIA = ["admin", "corregedoria_gestor", "corregedoria_analista"]
PERFIS_ZONA = ["chefe_cartorio", "substituto"]
PERIODICIDADES = ["diariamente", "semanalmente", "quinzenalmente", "mensalmente", "bimestralmente", "trimestralmente", "anualmente", "por demanda"]
GRUPOS_PADRAO = ["ELO", "SISTEMAS DA INTRANET", "OBSERVAÇÕES", "OUTROS"]
STATUS_TAREFA = ["pendente", "atrasado", "em_analise", "validado", "devolvido", "cumprido", "cumprido_com_ressalva", "nao_se_aplica"]
STATUS_CHECKLIST_ZONA = ["cumprido", "cumprido_com_ressalva", "nao_se_aplica", "pendente"]
TABELAS_BACKUP = [
    "perfis", "zonas_eleitorais", "municipios_zona", "usuarios", "itens_monitoramento",
    "ciclos_monitoramento", "tarefas_zona", "respostas", "validacoes_corregedoria",
    "comentarios_tarefa", "anexos_tarefa", "logs_auditoria", "configuracoes_sistema"
]

# ============================================================
# ESTILO VISUAL: SEM MENU LATERAL
# ============================================================

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none !important; visibility:hidden !important; width:0 !important; min-width:0 !important;}
    .block-container {padding-top:1.1rem; max-width:1450px;}
    .main-header {background:linear-gradient(120deg,#0F2F52,#174A7C 55%,#EAF3FF);padding:18px 22px;border-radius:18px;color:white;margin-bottom:12px;border:1px solid #D7E0EA;display:flex;align-items:center;gap:18px;box-shadow:0 8px 22px rgba(15,47,82,.14);}
    .main-header img {background:white;border-radius:14px;padding:8px;max-width:180px;max-height:70px;object-fit:contain;}
    .main-header h1 {font-size:24px;margin:0;color:white;line-height:1.25;}
    .main-header p {font-size:13px;margin:4px 0;color:#EAF3FF;}
    .auth-hero {background:#DCE7F3;border:1px solid #C6D2E1;border-radius:18px;padding:28px 24px 26px 24px;margin-bottom:18px;box-shadow:0 4px 16px rgba(15,47,82,.06);}
    .auth-logo-band {background:linear-gradient(90deg,#EEF4FB 0%, #F8FAFD 100%);border-radius:18px;padding:18px 26px;display:flex;align-items:center;justify-content:center;min-height:150px;margin:0 auto 20px auto;max-width:820px;}
    .auth-logo-band img {max-width:100%;width:min(760px, 92%);max-height:140px;object-fit:contain;display:block;}
    .auth-title {text-align:center;font-size:25px;line-height:1.28;font-weight:900;color:#174A7C;margin:6px 0 8px 0;}
    .auth-subtitle {text-align:center;font-size:14px;color:#415466;margin:0 auto;max-width:980px;}
    .banner {border-radius:18px;padding:18px 22px;margin:12px 0 18px 0;border:1px solid #D7E0EA;box-shadow:0 8px 20px rgba(15,47,82,.06);}
    .banner.corregedoria {background:linear-gradient(120deg,#0F2F52,#174A7C);color:white;}
    .banner.zona {background:linear-gradient(120deg,#EAF3FF,#FFFFFF);color:#174A7C;border-left:7px solid #174A7C;}
    .banner h2 {margin:0 0 8px 0;font-size:25px;font-weight:900;}
    .banner p {margin:4px 0;font-size:14px;line-height:1.45;}
    .card {background:white;border:1px solid #D7E0EA;border-radius:16px;padding:16px;box-shadow:0 6px 16px rgba(15,47,82,.06);min-height:120px;}
    .card h3 {font-size:18px;color:#174A7C;margin:0 0 8px 0;font-weight:900;}
    .card p {font-size:13px;color:#475569;margin:0 0 8px 0;line-height:1.42;}
    .step-flow {display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 16px 0;}
    .step-flow span {background:#EAF3FF;border:1px solid #BFDBFE;color:#174A7C;border-radius:999px;padding:8px 12px;font-weight:800;font-size:13px;}
    .metric-card {background:white;border:1px solid #D7E0EA;border-left:5px solid #174A7C;border-radius:14px;padding:13px 14px;min-height:95px;box-shadow:0 4px 12px rgba(15,47,82,.07);}
    .metric-card .label {font-size:12px;font-weight:800;color:#4B5563;text-transform:uppercase;}
    .metric-card .value {font-size:28px;font-weight:900;color:#174A7C;}
    div[data-testid="stButton"] button {border-radius:10px;font-weight:800;border:1px solid #174A7C;}
    div[data-testid="stButton"] button[kind="primary"] {background:#174A7C;border-color:#174A7C;color:white;}
    div[role="radiogroup"] {gap:.35rem;}
    div[role="radiogroup"] label {background:#F8FAFC;border:1px solid #CBD5E1;border-radius:999px;padding:6px 10px;margin-right:4px;font-weight:800;}
    div[data-testid="stDataFrame"] {border:1px solid #D7E0EA;border-radius:12px;overflow:hidden;}
    .small-note {font-size:12px;color:#64748B;}
    .danger-box {border-left:6px solid #B91C1C;background:#FEF2F2;border-radius:12px;padding:12px;margin:10px 0;color:#7F1D1D;}
    .ok-box {border-left:6px solid #15803D;background:#F0FDF4;border-radius:12px;padding:12px;margin:10px 0;color:#14532D;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def agora_brasilia() -> datetime:
    return datetime.now(timezone.utc).astimezone(FUSO_HORARIO_BRASILIA).replace(microsecond=0)


def hoje_brasilia() -> date:
    return agora_brasilia().date()


def fmt_data(valor) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass
    if isinstance(valor, datetime):
        return valor.strftime(FORMATO_DATA_HORA)
    if isinstance(valor, date):
        return valor.strftime(FORMATO_DATA)
    try:
        s = str(valor)
        return pd.to_datetime(valor).strftime(FORMATO_DATA_HORA if ":" in s or "T" in s else FORMATO_DATA)
    except Exception:
        return str(valor)


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def email_institucional(email: str) -> bool:
    return normalizar_email(email).endswith(DOMINIO_INSTITUCIONAL)


def get_query_param(nome: str) -> str | None:
    try:
        valor = st.query_params.get(nome)
        if isinstance(valor, list):
            return valor[0] if valor else None
        return valor
    except Exception:
        return None


def base_url() -> str:
    try:
        return st.secrets.get("APP_BASE_URL") or os.getenv("APP_BASE_URL", APP_BASE_URL_DEFAULT)
    except Exception:
        return os.getenv("APP_BASE_URL", APP_BASE_URL_DEFAULT)


def gerar_link_validacao(token: str) -> str:
    base = base_url().rstrip("/")
    return f"{base}/?validar={token}" if base else f"?validar={token}"


def gerar_link_recuperacao(token: str) -> str:
    base = base_url().rstrip("/")
    return f"{base}/?recuperar={token}" if base else f"?recuperar={token}"


def enviar_email(destinatario: str, assunto: str, corpo: str):
    try:
        smtp_host = st.secrets.get("SMTP_HOST", os.getenv("SMTP_HOST", ""))
        smtp_port = int(st.secrets.get("SMTP_PORT", os.getenv("SMTP_PORT", 587)))
        smtp_user = st.secrets.get("SMTP_USER", os.getenv("SMTP_USER", ""))
        smtp_password = st.secrets.get("SMTP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))
        remetente = st.secrets.get("EMAIL_REMETENTE", os.getenv("EMAIL_REMETENTE", smtp_user))
    except Exception:
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        remetente = os.getenv("EMAIL_REMETENTE", smtp_user)

    if not smtp_host or not smtp_user or not smtp_password or not remetente:
        return False, "E-mail SMTP não configurado."

    try:
        msg = EmailMessage()
        msg["From"] = remetente
        msg["To"] = destinatario
        msg["Subject"] = assunto
        msg.set_content(corpo)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        return True, "E-mail enviado."
    except Exception as e:
        return False, f"Falha ao enviar e-mail: {e}"


def dataframe(sql: str, **params) -> pd.DataFrame:
    with db_session() as conn:
        df = pd.read_sql_query(text(sql), conn, params=params)
    for col in df.columns:
        if any(x in col.lower() for x in ["data", "prazo", "periodo", "criado", "atualizado", "enviado", "validado", "login"]):
            try:
                df[col] = df[col].apply(fmt_data)
            except Exception:
                pass
    return df


def executar(sql: str, **params):
    with db_session() as conn:
        return conn.execute(text(sql), params)


@st.cache_resource(show_spinner=False)
def preparar_banco_once() -> bool:
    run_schema()
    with db_session() as conn:
        for nome, descricao in PERFIS:
            conn.execute(text("insert into perfis (nome, descricao) values (:n,:d) on conflict (nome) do update set descricao=excluded.descricao"), {"n": nome, "d": descricao})
        admin_email = st.secrets.get("ADMIN_EMAIL", os.getenv("ADMIN_EMAIL", "vitormps7@gmail.com"))
        admin_password = st.secrets.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "Admin2026"))
        perfil_admin = conn.execute(text("select id from perfis where nome='admin'")).scalar_one()
        existe = conn.execute(text("select id from usuarios where email=:email"), {"email": admin_email}).scalar()
        if not existe:
            conn.execute(text("""
                insert into usuarios (nome, email, senha_hash, perfil_id, ativo, validado, secao_operador)
                values ('Administrador', :email, :senha, :perfil, true, true, :secao)
            """), {"email": admin_email, "senha": hash_password(admin_password), "perfil": perfil_admin, "secao": UNIDADE_CORREGEDORIA})
    return True


def garantir_banco() -> bool:
    try:
        preparar_banco_once()
        return True
    except Exception as e:
        st.error(f"Não foi possível conectar ao banco: {e}")
        return False


def usuario_logado() -> dict:
    return st.session_state.get("user", {})


def perfil_atual() -> str:
    return usuario_logado().get("perfil", "")


def eh_corregedoria() -> bool:
    return perfil_atual() in PERFIS_CORREGEDORIA


def eh_zona() -> bool:
    return perfil_atual() in PERFIS_ZONA


def registrar_auditoria(acao: str, entidade: str, entidade_id=None, detalhe: str | None = None):
    try:
        u = usuario_logado()
        with db_session() as conn:
            conn.execute(text("""
                insert into logs_auditoria (usuario_id, usuario_nome, usuario_email, acao, entidade, entidade_id, detalhe, criado_em)
                values (:uid, :nome, :email, :acao, :entidade, :eid, :detalhe, (now() at time zone 'America/Sao_Paulo'))
            """), {"uid": u.get("id"), "nome": u.get("nome"), "email": u.get("email"), "acao": acao, "entidade": entidade, "eid": entidade_id, "detalhe": detalhe})
    except Exception:
        pass


def zonas_options(incluir_todas=False):
    if not garantir_banco():
        return []
    df = dataframe("select id, lpad(numero::text,3,'0') || 'ª ZE - ' || coalesce(municipio_sede,'A definir') || '/BA' as label from zonas_eleitorais order by numero")
    opts = []
    if incluir_todas:
        opts.append((None, "Todas as Zonas"))
    opts.extend([(int(r["id"]), r["label"]) for _, r in df.iterrows()])
    return opts

# ============================================================
# ACESSO, CADASTRO E RECUPERAÇÃO DE SENHA
# ============================================================

def processar_validacao() -> bool:
    token = get_query_param("validar")
    if not token:
        return False
    if not garantir_banco():
        return True
    with db_session() as conn:
        row = conn.execute(text("select id, email from usuarios where token_validacao=:t"), {"t": token}).mappings().first()
        if not row:
            st.error("Link de validação inválido ou já utilizado.")
            return True
        conn.execute(text("update usuarios set validado=true, token_validacao=null, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"id": row["id"]})
    st.success("Cadastro validado com sucesso. Faça login para acessar o sistema.")
    registrar_auditoria("validacao_cadastro", "usuarios", row["id"], row["email"])
    return True


def processar_recuperacao() -> bool:
    token = get_query_param("recuperar")
    if not token:
        return False
    if not garantir_banco():
        return True
    with db_session() as conn:
        row = conn.execute(text("""
            select id, email from usuarios
            where token_recuperacao=:t and token_recuperacao_expira_em >= (now() at time zone 'America/Sao_Paulo')
        """), {"t": token}).mappings().first()
    if not row:
        st.error("Link de recuperação inválido ou expirado.")
        return True
    st.markdown(f"### Redefinir senha de {row['email']}")
    with st.form("nova_senha"):
        nova = st.text_input("Nova senha", type="password")
        confirma = st.text_input("Confirmar nova senha", type="password")
        salvar = st.form_submit_button("Salvar nova senha", type="primary")
    if salvar:
        if len(nova or "") < 6:
            st.warning("A senha deve ter pelo menos 6 caracteres.")
        elif nova != confirma:
            st.warning("As senhas não conferem.")
        else:
            with db_session() as conn:
                conn.execute(text("""
                    update usuarios set senha_hash=:h, token_recuperacao=null, token_recuperacao_expira_em=null,
                    atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id
                """), {"h": hash_password(nova), "id": row["id"]})
            st.success("Senha redefinida com sucesso. Faça login novamente.")
            registrar_auditoria("recuperacao_senha", "usuarios", row["id"], row["email"])
    return True


def login_box():
    st.markdown(f"""
    <div class="auth-hero">
        <div class="auth-logo-band"><img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}"></div>
        <div class="auth-title">SIMOC-BA - Sistema de Monitoramento Cartorário</div>
        <div class="auth-subtitle">Corregedoria cadastra atividades e periodicidade; Zona executa, informa responsável e marca o checklist.</div>
    </div>
    """, unsafe_allow_html=True)

    if processar_validacao() or processar_recuperacao():
        return

    aba_login, aba_cadastro, aba_recuperar = st.tabs(["Entrar", "Cadastrar usuário", "Recuperar senha"])

    with aba_login:
        st.subheader("Acesso ao sistema")
        with st.form("login"):
            email = normalizar_email(st.text_input("E-mail"))
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
            if not garantir_banco():
                return
            with db_session() as conn:
                row = conn.execute(text("""
                    select u.id, u.nome, u.email, u.senha_hash, u.zona_eleitoral_id, p.nome as perfil, u.validado, u.ativo
                    from usuarios u join perfis p on p.id = u.perfil_id
                    where u.email=:email
                """), {"email": email}).mappings().first()
                if not row or not row["ativo"] or not verify_password(senha, row["senha_hash"]):
                    st.error("Usuário ou senha inválidos.")
                elif not row["validado"]:
                    st.warning("Cadastro ainda não validado. Use o link enviado ao e-mail ou solicite validação à Corregedoria.")
                else:
                    conn.execute(text("update usuarios set ultimo_login=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"id": row["id"]})
                    st.session_state.user = {k: v for k, v in dict(row).items() if k != "senha_hash"}
                    registrar_auditoria("login", "usuarios", row["id"], email)
                    st.rerun()

    with aba_cadastro:
        st.subheader("Cadastrar usuário")
        st.caption("Cadastro preferencialmente com e-mail institucional. Usuários de Zona devem estar vinculados à Zona Eleitoral correspondente.")
        if not garantir_banco():
            return
        zopts = zonas_options()
        with st.form("cadastro_usuario"):
            nome = st.text_input("Nome completo")
            email = normalizar_email(st.text_input("E-mail institucional"))
            perfil = st.selectbox("Tipo de acesso", ["chefe_cartorio", "substituto", "corregedoria_analista"], format_func=lambda x: {"chefe_cartorio":"Chefe de Cartório/Zona", "substituto":"Substituto da Zona", "corregedoria_analista":"Analista da Corregedoria"}.get(x,x))
            zona_id = None
            if perfil in PERFIS_ZONA:
                label = st.selectbox("Zona vinculada", [lbl for _, lbl in zopts] if zopts else [])
                for zid, lbl in zopts:
                    if lbl == label:
                        zona_id = zid
            senha = st.text_input("Senha", type="password")
            confirmar = st.text_input("Confirmar senha", type="password")
            submitted = st.form_submit_button("Cadastrar")
        if submitted:
            if not nome.strip():
                st.warning("Informe o nome.")
            elif not email:
                st.warning("Informe o e-mail.")
            elif not email_institucional(email):
                st.warning(f"O e-mail deve terminar com {DOMINIO_INSTITUCIONAL}.")
            elif perfil in PERFIS_ZONA and not zona_id:
                st.warning("Selecione a Zona vinculada.")
            elif len(senha or "") < 6:
                st.warning("A senha deve ter pelo menos 6 caracteres.")
            elif senha != confirmar:
                st.warning("As senhas não conferem.")
            else:
                token = secrets.token_urlsafe(32)
                with db_session() as conn:
                    perfil_id = conn.execute(text("select id from perfis where nome=:p"), {"p": perfil}).scalar_one()
                    existe = conn.execute(text("select id from usuarios where email=:e"), {"e": email}).scalar()
                    if existe:
                        st.warning("Este e-mail já está cadastrado.")
                    else:
                        uid = conn.execute(text("""
                            insert into usuarios (nome,email,senha_hash,perfil_id,zona_eleitoral_id,ativo,validado,token_validacao,secao_operador)
                            values (:n,:e,:s,:p,:z,true,false,:t,:secao) returning id
                        """), {"n": nome.strip(), "e": email, "s": hash_password(senha), "p": perfil_id, "z": zona_id, "t": token, "secao": UNIDADE_CORREGEDORIA}).scalar_one()
                        link = gerar_link_validacao(token)
                        ok, msg = enviar_email(
                            email,
                            f"Validação de cadastro - {NOME_SISTEMA}",
                            f"Olá, {nome}.\n\nPara validar seu acesso ao {NOME_SISTEMA}, acesse:\n\n{link}\n\nCaso não tenha solicitado, ignore esta mensagem."
                        )
                        registrar_auditoria("cadastro_usuario", "usuarios", uid, email)
                        if ok:
                            st.success("Cadastro realizado. Link de validação enviado ao e-mail informado.")
                        else:
                            st.warning(f"{msg} Link de validação gerado: {link}")

    with aba_recuperar:
        st.subheader("Recuperar senha")
        st.caption("Use esta opção apenas para usuário já cadastrado.")
        email_rec = normalizar_email(st.text_input("E-mail cadastrado", key="email_recuperacao"))
        if st.button("Gerar link de recuperação"):
            if not garantir_banco():
                return
            with db_session() as conn:
                row = conn.execute(text("select id, nome, email from usuarios where email=:e and ativo=true"), {"e": email_rec}).mappings().first()
                if not row:
                    st.error("E-mail não encontrado.")
                else:
                    token = secrets.token_urlsafe(32)
                    expira = agora_brasilia() + timedelta(hours=2)
                    conn.execute(text("""
                        update usuarios set token_recuperacao=:t, token_recuperacao_expira_em=:expira,
                        atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id
                    """), {"t": token, "expira": expira.replace(tzinfo=None), "id": row["id"]})
                    link = gerar_link_recuperacao(token)
                    ok, msg = enviar_email(
                        row["email"],
                        f"Recuperação de senha - {NOME_SISTEMA}",
                        f"Recebemos uma solicitação de recuperação de senha para o {NOME_SISTEMA}.\n\nAcesse o link abaixo para criar uma nova senha:\n\n{link}\n\nO link expira em 2 horas. Caso você não tenha solicitado, ignore esta mensagem."
                    )
                    registrar_auditoria("gerar_recuperacao_senha", "usuarios", row["id"], row["email"])
                    if ok:
                        st.success("Link de recuperação enviado ao e-mail cadastrado.")
                    else:
                        st.warning(f"{msg} Link de recuperação de senha gerado: {link}")

# ============================================================
# LAYOUT
# ============================================================

def header():
    u = usuario_logado()
    st.markdown(f"""
    <div class="main-header">
        <img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}">
        <div>
            <h1>SIMOC-BA - Monitoramento Cartorário</h1>
            <p>{NOME_COMPLETO} | Data e horário de Brasília</p>
            <p>Usuário: <b>{u.get('nome','')}</b> · Perfil: <b>{u.get('perfil','')}</b></p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    col1, col2 = st.columns([5, 1])
    with col2:
        if st.button("Sair", use_container_width=True):
            registrar_auditoria("logout", "usuarios", u.get("id"))
            st.session_state.clear()
            st.rerun()


def nav_pages():
    if eh_corregedoria():
        return ["Início", "Atividades", "Acompanhamento", "Validar", "Zonas", "Relatórios", "Backup", "Usuários", "Auditoria"]
    if eh_zona():
        return ["Início", "Checklist", "Orientações"]
    return ["Acompanhamento", "Zonas", "Relatórios"]

# ============================================================
# CONSULTAS DE TAREFAS E RELATÓRIOS
# ============================================================

def tarefas_sql(where_extra="", order="t.prazo asc, z.numero asc", limit=1000):
    return f"""
        select t.id as tarefa_id, lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.numero as zona_numero,
               coalesce(z.municipio_sede,'A definir') as municipio_sede, i.grupo, i.descricao as atividade,
               i.frequencia as periodicidade, i.responsavel_origem as responsavel_referencia,
               i.orientacao_corregedoria, c.periodo_inicio, c.periodo_fim, t.prazo, t.status,
               t.responsavel_atividade_zona, t.data_execucao, t.observacao_corregedoria,
               t.criado_em, t.atualizado_em
        from tarefas_zona t
        join zonas_eleitorais z on z.id=t.zona_eleitoral_id
        join itens_monitoramento i on i.id=t.item_monitoramento_id
        join ciclos_monitoramento c on c.id=t.ciclo_id
        where 1=1 {where_extra}
        order by {order}
        limit {int(limit)}
    """


def tarefas_df(status=None, zona_id=None, grupo=None, periodicidade=None, data_ini=None, data_fim=None, limit=1000):
    clauses = []
    params = {}
    if status:
        clauses.append("and t.status = any(:status)")
        params["status"] = status
    if zona_id:
        clauses.append("and t.zona_eleitoral_id=:zona")
        params["zona"] = zona_id
    if grupo:
        clauses.append("and i.grupo=:grupo")
        params["grupo"] = grupo
    if periodicidade:
        clauses.append("and i.frequencia=:periodicidade")
        params["periodicidade"] = periodicidade
    if data_ini:
        clauses.append("and c.periodo_fim >= :data_ini")
        params["data_ini"] = data_ini
    if data_fim:
        clauses.append("and c.periodo_inicio <= :data_fim")
        params["data_fim"] = data_fim
    return dataframe(tarefas_sql(" ".join(clauses), limit=limit), **params)


def status_real_tarefa(row) -> str:
    try:
        prazo = pd.to_datetime(row.get("prazo"), dayfirst=True).date() if not isinstance(row.get("prazo"), date) else row.get("prazo")
        if row.get("status") == "pendente" and prazo and prazo < hoje_brasilia():
            return "atrasado"
    except Exception:
        pass
    return row.get("status") or "pendente"

# ============================================================
# PÁGINAS DA CORREGEDORIA
# ============================================================

def page_inicio_corregedoria():
    st.markdown("""
    <div class="banner corregedoria">
        <h2>Interface da Corregedoria</h2>
        <p><b>Fluxo:</b> cadastrar atividades monitoradas, definir periodicidade e período, gerar checklist para as Zonas, acompanhar realização e validar as respostas.</p>
    </div>
    <div class="step-flow">
        <span>1. Cadastrar atividade</span><span>2. Definir periodicidade</span><span>3. Gerar checklist</span><span>4. Zona executa</span><span>5. Corregedoria valida</span>
    </div>
    """, unsafe_allow_html=True)
    df = dataframe("select status, count(*) as total from tarefas_zona group by status")
    totais = dict(zip(df.get("status", []), df.get("total", []))) if not df.empty else {}
    cols = st.columns(5)
    for col, label, key in zip(cols, ["Pendentes", "Em análise", "Validadas", "Devolvidas", "Total"], ["pendente", "em_analise", "validado", "devolvido", "total"]):
        val = sum(totais.values()) if key == "total" else totais.get(key, 0)
        col.markdown(f"<div class='metric-card'><div class='label'>{label}</div><div class='value'>{val}</div></div>", unsafe_allow_html=True)
    st.info("Use a aba **Atividades** para cadastrar atividades e gerar checklist para as Zonas. A aba **Acompanhamento** mostra o controle de realização.")


def page_atividades():
    st.header("Atividades monitoradas e geração de checklist")
    st.caption("A Corregedoria cadastra a atividade, define periodicidade, período de execução e prazo para a Zona preencher. Depois gera o checklist para uma Zona ou todas as Zonas.")
    aba_cadastro, aba_gerar, aba_lista = st.tabs(["Cadastrar atividade", "Gerar checklist para Zonas", "Atividades cadastradas"])

    with aba_cadastro:
        with st.form("form_item"):
            c1, c2 = st.columns(2)
            with c1:
                grupo = st.selectbox("Grupo", GRUPOS_PADRAO)
                descricao = st.text_area("Atividade a ser monitorada", height=120, placeholder="Ex.: RAE em diligência")
                periodicidade = st.selectbox("Periodicidade de acompanhamento", PERIODICIDADES)
                responsavel_ref = st.text_input("Responsável de referência da planilha", placeholder="Ex.: Emerson e Rosy")
            with c2:
                prazo_padrao = st.number_input("Prazo padrão para preenchimento pela Zona, em dias", min_value=0, max_value=365, value=7)
                exige_evidencia = st.checkbox("Exigir evidência/link SEI/comprovante", value=False)
                criticidade = st.selectbox("Criticidade", ["baixa", "media", "alta"], index=1)
                ativo = st.checkbox("Atividade ativa", value=True)
            orientacao = st.text_area("Orientação da Corregedoria para a Zona", height=120)
            salvar = st.form_submit_button("Salvar atividade monitorada", type="primary")
        if salvar:
            if not descricao.strip():
                st.warning("Informe a atividade.")
            else:
                with db_session() as conn:
                    item_id = conn.execute(text("""
                        insert into itens_monitoramento (grupo, descricao, responsavel_origem, frequencia, exige_evidencia, criticidade, ativo, orientacao_corregedoria, prazo_padrao_dias, atualizado_em)
                        values (:grupo,:desc,:resp,:freq,:evid,:crit,:ativo,:orient,:prazo,(now() at time zone 'America/Sao_Paulo'))
                        on conflict (grupo, descricao) do update set
                          responsavel_origem=excluded.responsavel_origem,
                          frequencia=excluded.frequencia,
                          exige_evidencia=excluded.exige_evidencia,
                          criticidade=excluded.criticidade,
                          ativo=excluded.ativo,
                          orientacao_corregedoria=excluded.orientacao_corregedoria,
                          prazo_padrao_dias=excluded.prazo_padrao_dias,
                          atualizado_em=(now() at time zone 'America/Sao_Paulo')
                        returning id
                    """), {"grupo": grupo, "desc": descricao.strip(), "resp": responsavel_ref.strip(), "freq": periodicidade, "evid": exige_evidencia, "crit": criticidade, "ativo": ativo, "orient": orientacao, "prazo": int(prazo_padrao)}).scalar_one()
                registrar_auditoria("salvar_atividade_monitorada", "itens_monitoramento", item_id, descricao[:120])
                st.success("Atividade salva. Agora gere o checklist para as Zonas na próxima aba.")

    with aba_gerar:
        itens = dataframe("select id, grupo || ' - ' || descricao || ' [' || frequencia || ']' as label, prazo_padrao_dias from itens_monitoramento where ativo=true order by grupo, descricao")
        if itens.empty:
            st.warning("Cadastre uma atividade antes de gerar checklist.")
        else:
            with st.form("form_gerar_checklist"):
                item_label = st.selectbox("Atividade", itens["label"].tolist())
                item_id = int(itens.loc[itens["label"] == item_label, "id"].iloc[0])
                prazo_padrao = int(itens.loc[itens["label"] == item_label, "prazo_padrao_dias"].iloc[0] or 0)
                c1, c2, c3 = st.columns(3)
                with c1:
                    periodo_inicio = st.date_input("Início do período de execução", value=hoje_brasilia(), format="DD/MM/YYYY")
                with c2:
                    periodo_fim = st.date_input("Fim do período de execução", value=hoje_brasilia(), format="DD/MM/YYYY")
                with c3:
                    prazo = st.date_input("Prazo para a Zona preencher", value=hoje_brasilia() + timedelta(days=prazo_padrao or 7), format="DD/MM/YYYY")
                destino_tipo = st.radio("Destino", ["Todas as Zonas", "Apenas uma Zona"], horizontal=True)
                zona_id = None
                if destino_tipo == "Apenas uma Zona":
                    zopts = zonas_options()
                    label = st.selectbox("Zona de destino", [lbl for _, lbl in zopts])
                    for zid, lbl in zopts:
                        if lbl == label:
                            zona_id = zid
                gerar = st.form_submit_button("Gerar checklist", type="primary")
            if gerar:
                if periodo_fim < periodo_inicio:
                    st.warning("O fim do período não pode ser anterior ao início.")
                elif prazo < periodo_inicio:
                    st.warning("O prazo deve ser igual ou posterior ao início do período.")
                else:
                    with db_session() as conn:
                        periodicidade = conn.execute(text("select frequencia from itens_monitoramento where id=:id"), {"id": item_id}).scalar_one()
                        ciclo_id = conn.execute(text("""
                            insert into ciclos_monitoramento (periodo_inicio, periodo_fim, tipo_periodicidade, status, criado_em)
                            values (:ini,:fim,:tipo,'aberto',(now() at time zone 'America/Sao_Paulo'))
                            on conflict (periodo_inicio, periodo_fim, tipo_periodicidade) do update set status='aberto'
                            returning id
                        """), {"ini": periodo_inicio, "fim": periodo_fim, "tipo": periodicidade}).scalar_one()
                        if destino_tipo == "Todas as Zonas":
                            zonas = conn.execute(text("select id from zonas_eleitorais where ativa=true order by numero")).scalars().all()
                        else:
                            zonas = [zona_id]
                        criadas = 0
                        for zid in zonas:
                            if zid:
                                res = conn.execute(text("""
                                    insert into tarefas_zona (zona_eleitoral_id, item_monitoramento_id, ciclo_id, prazo, status, criado_em, atualizado_em)
                                    values (:z,:item,:ciclo,:prazo,'pendente',(now() at time zone 'America/Sao_Paulo'),(now() at time zone 'America/Sao_Paulo'))
                                    on conflict (zona_eleitoral_id, item_monitoramento_id, ciclo_id) do nothing
                                """), {"z": zid, "item": item_id, "ciclo": ciclo_id, "prazo": prazo})
                                criadas += res.rowcount or 0
                    registrar_auditoria("gerar_checklist_zonas", "tarefas_zona", None, f"item={item_id}; criadas={criadas}")
                    st.success(f"Checklist gerado. Novas tarefas criadas: {criadas}. Tarefas já existentes foram preservadas.")

    with aba_lista:
        filtro = st.text_input("Filtrar atividade")
        st.dataframe(dataframe("""
            select id, grupo, descricao as atividade, frequencia as periodicidade, responsavel_origem as responsavel_referencia,
                   prazo_padrao_dias, exige_evidencia, criticidade, ativo, orientacao_corregedoria, atualizado_em
            from itens_monitoramento
            where (:filtro='' or descricao ilike :like or grupo ilike :like or coalesce(responsavel_origem,'') ilike :like)
            order by grupo, descricao
        """, filtro=filtro, like=f"%{filtro}%"), use_container_width=True, hide_index=True)


def page_acompanhamento():
    st.header("Acompanhamento da realização pelas Zonas")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        status = st.multiselect("Status", STATUS_TAREFA, default=["pendente", "atrasado", "em_analise", "devolvido"])
    with c2:
        periodicidade = st.selectbox("Periodicidade", ["Todas"] + PERIODICIDADES)
    with c3:
        grupo = st.selectbox("Grupo", ["Todos"] + GRUPOS_PADRAO)
    with c4:
        limite = st.number_input("Limite", 50, 5000, 500, 50)
    zopts = zonas_options(incluir_todas=True)
    zona_label = st.selectbox("Zona", [lbl for _, lbl in zopts]) if zopts else "Todas as Zonas"
    zona_id = next((zid for zid, lbl in zopts if lbl == zona_label), None)
    df = tarefas_df(status=status or None, zona_id=zona_id, grupo=None if grupo == "Todos" else grupo, periodicidade=None if periodicidade == "Todas" else periodicidade, limit=int(limite))
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_validacao():
    st.header("Validar checklist enviado pela Zona")
    df = dataframe("""
        select distinct on (r.tarefa_zona_id) r.id as resposta_id, t.id as tarefa_id,
               lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.municipio_sede, i.grupo, i.descricao as atividade,
               i.frequencia as periodicidade, t.responsavel_atividade_zona, t.data_execucao, r.status as resposta,
               r.observacao, r.justificativa, r.evidencia_url, r.enviado_em
        from respostas r
        join tarefas_zona t on t.id=r.tarefa_zona_id
        join zonas_eleitorais z on z.id=t.zona_eleitoral_id
        join itens_monitoramento i on i.id=t.item_monitoramento_id
        where t.status='em_analise'
        order by r.tarefa_zona_id, r.enviado_em desc
        limit 500
    """)
    st.dataframe(df, use_container_width=True, hide_index=True)
    if df.empty:
        st.success("Não há checklists aguardando validação.")
        return
    resposta_id = st.selectbox("Resposta a decidir", df["resposta_id"].tolist())
    tarefa_id = int(df.loc[df["resposta_id"] == resposta_id, "tarefa_id"].iloc[0])
    acao = st.radio("Decisão da Corregedoria", ["validado", "devolvido"], horizontal=True)
    obs = st.text_area("Observação da Corregedoria")
    if st.button("Registrar decisão", type="primary"):
        with db_session() as conn:
            conn.execute(text("""
                insert into validacoes_corregedoria (resposta_id, usuario_corregedoria_id, status_validacao, observacao, validado_em)
                values (:resposta,:usuario,:status,:obs,(now() at time zone 'America/Sao_Paulo'))
            """), {"resposta": int(resposta_id), "usuario": usuario_logado()["id"], "status": acao, "obs": obs})
            conn.execute(text("update tarefas_zona set status=:status, observacao_corregedoria=:obs, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"status": acao, "obs": obs, "id": tarefa_id})
        registrar_auditoria("corregedoria_valida_checklist", "tarefas_zona", tarefa_id, acao)
        st.success("Decisão registrada.")
        st.rerun()

# ============================================================
# PÁGINAS DA ZONA
# ============================================================

def page_inicio_zona():
    u = usuario_logado()
    st.markdown("""
    <div class="banner zona">
        <h2>Interface da Zona Eleitoral</h2>
        <p><b>Função da Zona:</b> executar as atividades encaminhadas pela Corregedoria, informar o responsável local, marcar o checklist e enviar para análise.</p>
    </div>
    <div class="step-flow">
        <span>1. Ver checklist</span><span>2. Executar atividade</span><span>3. Informar responsável</span><span>4. Marcar realização</span><span>5. Enviar à Corregedoria</span>
    </div>
    """, unsafe_allow_html=True)
    if not u.get("zona_eleitoral_id"):
        st.warning("Seu usuário ainda não está vinculado a uma Zona Eleitoral. Solicite ajuste à Corregedoria.")
        return
    df = tarefas_df(zona_id=u.get("zona_eleitoral_id"), limit=1000)
    st.write(f"Tarefas vinculadas à sua Zona: **{len(df)}**")
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)


def page_checklist_zona():
    st.header("Checklist da Zona")
    user = usuario_logado()
    zona_id = user.get("zona_eleitoral_id")
    if not zona_id:
        st.error("Usuário sem Zona vinculada. A Corregedoria precisa vincular seu cadastro a uma Zona Eleitoral.")
        return
    c1, c2 = st.columns(2)
    with c1:
        status = st.multiselect("Status", ["pendente", "devolvido", "em_analise", "validado"], default=["pendente", "devolvido"])
    with c2:
        periodicidade = st.selectbox("Periodicidade", ["Todas"] + PERIODICIDADES)
    df = tarefas_df(status=status or None, zona_id=zona_id, periodicidade=None if periodicidade == "Todas" else periodicidade, limit=500)
    st.dataframe(df, use_container_width=True, hide_index=True)
    if df.empty:
        st.info("Não há tarefas para preencher com os filtros atuais.")
        return
    tarefa_id = st.selectbox("Selecionar tarefa para preencher", df["tarefa_id"].tolist())
    linha = df[df["tarefa_id"] == tarefa_id].iloc[0].to_dict()
    st.markdown(f"""
    <div class="card">
        <h3>{linha.get('atividade')}</h3>
        <p><b>Grupo:</b> {linha.get('grupo')} · <b>Periodicidade:</b> {linha.get('periodicidade')} · <b>Prazo:</b> {linha.get('prazo')}</p>
        <p><b>Orientação da Corregedoria:</b> {linha.get('orientacao_corregedoria') or 'Sem orientação específica.'}</p>
    </div>
    """, unsafe_allow_html=True)
    with st.form("preencher_checklist"):
        responsavel = st.text_input("Responsável pela atividade na Zona", value=linha.get("responsavel_atividade_zona") or "")
        data_exec = st.date_input("Data de execução/conferência", value=hoje_brasilia(), format="DD/MM/YYYY")
        status_resposta = st.selectbox("Resultado do checklist", STATUS_CHECKLIST_ZONA)
        obs = st.text_area("Observação")
        justificativa = st.text_area("Justificativa, se houver")
        evidencia = st.text_input("Link da evidência, documento SEI ou comprovante")
        enviado = st.form_submit_button("Enviar para a Corregedoria", type="primary")
    if enviado:
        if not responsavel.strip():
            st.warning("Informe o responsável pela atividade na Zona.")
            return
        with db_session() as conn:
            conn.execute(text("""
                insert into respostas (tarefa_zona_id, usuario_id, status, observacao, justificativa, evidencia_url, enviado_em)
                values (:tarefa,:usuario,:status,:obs,:just,:evid,(now() at time zone 'America/Sao_Paulo'))
            """), {"tarefa": int(tarefa_id), "usuario": user["id"], "status": status_resposta, "obs": obs, "just": justificativa, "evid": evidencia})
            novo = "em_analise" if status_resposta in ["cumprido", "cumprido_com_ressalva", "nao_se_aplica"] else "pendente"
            conn.execute(text("""
                update tarefas_zona set status=:status, responsavel_atividade_zona=:resp, data_execucao=:data_exec,
                atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id
            """), {"status": novo, "resp": responsavel.strip(), "data_exec": data_exec, "id": int(tarefa_id)})
        registrar_auditoria("zona_marca_checklist", "tarefas_zona", int(tarefa_id), f"{status_resposta} - {responsavel}")
        st.success("Checklist enviado para visualização/validação da Corregedoria.")
        st.rerun()

# ============================================================
# ZONAS, USUÁRIOS, RELATÓRIOS, BACKUP E AUDITORIA
# ============================================================

def page_zonas():
    st.header("Zonas Eleitorais da Bahia")
    st.info("Cada Zona fica vinculada ao município-sede. Quando houver mais de um município abrangido, para fins de controle o sistema considera a sede.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Garantir relação 001 a 205", use_container_width=True):
            with db_session() as conn:
                total = seed_zonas_bahia_padrao(conn)
            st.success(f"Relação-base garantida: {total} zonas. Nenhum dado existente foi apagado.")
    with c2:
        if st.button("Importar/atualizar município-sede pelo TRE-BA", use_container_width=True):
            with st.spinner("Consultando página pública do TRE-BA..."):
                total = importar_zonas(TREBA_CONSULTA_CARTORIOS_URL)
            st.success(f"Importação concluída: {total} zonas atualizadas.")
    filtro = st.text_input("Filtrar Zona ou município-sede")
    st.dataframe(dataframe("""
        select id, lpad(numero::text,3,'0') as zona, municipio_sede, municipios_abrangidos, email, telefone, chefe_cartorio, juiz_eleitoral, ativa
        from zonas_eleitorais
        where (:filtro='' or cast(numero as text) like :like or coalesce(municipio_sede,'') ilike :like)
        order by numero
    """, filtro=filtro, like=f"%{filtro}%"), use_container_width=True, hide_index=True)


def page_usuarios():
    st.header("Usuários e vinculação de Zona")
    if not eh_corregedoria():
        st.error("Apenas a Corregedoria administra usuários.")
        return
    with st.form("usuario"):
        c1, c2, c3 = st.columns(3)
        with c1:
            nome = st.text_input("Nome")
            email = normalizar_email(st.text_input("E-mail"))
            senha = st.text_input("Senha inicial ou nova senha", type="password")
        with c2:
            perfil = st.selectbox("Perfil", [p[0] for p in PERFIS])
            ativo = st.checkbox("Ativo", value=True)
            validado = st.checkbox("Validado", value=True)
        with c3:
            zopts = zonas_options()
            zona_id = None
            label = st.selectbox("Zona vinculada, se perfil de Zona", ["Sem zona"] + [lbl for _, lbl in zopts])
            if label != "Sem zona":
                zona_id = next((zid for zid, lbl in zopts if lbl == label), None)
        salvar = st.form_submit_button("Salvar usuário", type="primary")
    if salvar:
        if not nome or not email:
            st.warning("Informe nome e e-mail.")
            return
        with db_session() as conn:
            perfil_id = conn.execute(text("select id from perfis where nome=:p"), {"p": perfil}).scalar_one()
            existe = conn.execute(text("select id from usuarios where email=:e"), {"e": email}).scalar()
            if existe:
                params = {"n": nome, "p": perfil_id, "z": zona_id, "a": ativo, "v": validado, "e": email}
                if senha:
                    params["s"] = hash_password(senha)
                    sql = """
                        update usuarios set nome=:n, perfil_id=:p, zona_eleitoral_id=:z, ativo=:a, validado=:v, senha_hash=:s,
                        atualizado_em=(now() at time zone 'America/Sao_Paulo') where email=:e
                    """
                else:
                    sql = """
                        update usuarios set nome=:n, perfil_id=:p, zona_eleitoral_id=:z, ativo=:a, validado=:v,
                        atualizado_em=(now() at time zone 'America/Sao_Paulo') where email=:e
                    """
                conn.execute(text(sql), params)
            else:
                if not senha:
                    st.warning("Informe senha inicial para novo usuário.")
                    return
                conn.execute(text("""
                    insert into usuarios (nome,email,senha_hash,perfil_id,zona_eleitoral_id,ativo,validado,secao_operador)
                    values (:n,:e,:s,:p,:z,:a,:v,:secao)
                """), {"n": nome, "e": email, "s": hash_password(senha), "p": perfil_id, "z": zona_id, "a": ativo, "v": validado, "secao": UNIDADE_CORREGEDORIA})
        registrar_auditoria("salvar_usuario", "usuarios", None, email)
        st.success("Usuário salvo.")
    st.dataframe(dataframe("""
        select u.nome, u.email, p.nome as perfil, lpad(z.numero::text,3,'0') || 'ª ZE - ' || coalesce(z.municipio_sede,'A definir') as zona, u.ativo, u.validado, u.ultimo_login
        from usuarios u join perfis p on p.id=u.perfil_id left join zonas_eleitorais z on z.id=u.zona_eleitoral_id
        order by p.nome, u.nome
    """), use_container_width=True, hide_index=True)


def montar_backup_completo() -> dict:
    backup = {
        "sistema": NOME_SISTEMA,
        "versao_backup": "simoc-ba-1.0",
        "gerado_em_brasilia": agora_brasilia().isoformat(),
        "tabelas": {},
    }
    with db_session() as conn:
        for tabela in TABELAS_BACKUP:
            try:
                rows = conn.execute(text(f"select * from {tabela}")).mappings().all()
                backup["tabelas"][tabela] = [dict(r) for r in rows]
            except Exception:
                backup["tabelas"][tabela] = []
    return backup


def bytes_json(obj: dict) -> bytes:
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, indent=2, default=default).encode("utf-8")


def page_backup():
    st.header("Backup e restauração")
    st.markdown("<div class='ok-box'><b>Backup seguro:</b> a geração de backup apenas lê os dados do Supabase e baixa um arquivo JSON. Não apaga nada.</div>", unsafe_allow_html=True)
    if st.button("Gerar backup completo agora", type="primary"):
        backup = montar_backup_completo()
        conteudo = bytes_json(backup)
        nome = f"backup_simoc_ba_{agora_brasilia().strftime('%Y%m%d_%H%M%S')}.json"
        digest = hashlib.sha256(conteudo).hexdigest()
        with db_session() as conn:
            conn.execute(text("""
                insert into backups_registros (nome_arquivo, tipo, quantidade_registros, gerado_por_usuario_id, gerado_por_nome, gerado_por_email, hash_sha256, criado_em)
                values (:nome,'json',:qtd,:uid,:unome,:email,:hash,(now() at time zone 'America/Sao_Paulo'))
            """), {"nome": nome, "qtd": sum(len(v) for v in backup["tabelas"].values()), "uid": usuario_logado().get("id"), "unome": usuario_logado().get("nome"), "email": usuario_logado().get("email"), "hash": digest})
        st.download_button("Baixar backup JSON", data=conteudo, file_name=nome, mime="application/json")
        st.success("Backup gerado. Guarde o arquivo em local seguro.")
    st.subheader("Restauração controlada")
    st.warning("Restauração pode alterar dados. Use apenas com orientação e após gerar backup atual.")
    arq = st.file_uploader("Selecionar backup JSON", type=["json"])
    confirm = st.text_input("Para habilitar restauração, digite: CONFIRMO RESTAURAR")
    if st.button("Restaurar backup selecionado"):
        if confirm != "CONFIRMO RESTAURAR":
            st.error("Confirmação não informada corretamente.")
        elif arq is None:
            st.error("Selecione um arquivo de backup.")
        else:
            dados = json.loads(arq.read().decode("utf-8"))
            tabelas = dados.get("tabelas", {})
            with db_session() as conn:
                # Restauração conservadora: usa DELETE/INSERT apenas em tabelas de operação. Perfis e zonas são preservados por segurança.
                for tabela in ["respostas", "validacoes_corregedoria", "comentarios_tarefa", "anexos_tarefa", "tarefas_zona", "ciclos_monitoramento", "itens_monitoramento"]:
                    rows = tabelas.get(tabela, [])
                    if not rows:
                        continue
                    conn.execute(text(f"delete from {tabela}"))
                    for row in rows:
                        cols = list(row.keys())
                        sql_cols = ",".join(cols)
                        sql_vals = ",".join([f":{c}" for c in cols])
                        conn.execute(text(f"insert into {tabela} ({sql_cols}) values ({sql_vals})"), row)
            registrar_auditoria("restaurar_backup", "backup", None, "restauração controlada")
            st.success("Backup restaurado parcialmente com segurança. Perfis, usuários e zonas foram preservados.")


def aplicar_filtros_relatorio():
    st.subheader("Filtros do relatório")
    c1, c2, c3 = st.columns(3)
    with c1:
        status = st.multiselect("Status", STATUS_TAREFA)
        periodicidade = st.selectbox("Periodicidade", ["Todas"] + PERIODICIDADES)
    with c2:
        grupo = st.selectbox("Grupo", ["Todos"] + GRUPOS_PADRAO)
        data_ini = st.date_input("Período de/desde", value=None, format="DD/MM/YYYY")
    with c3:
        zopts = zonas_options(incluir_todas=True)
        zona_label = st.selectbox("Zona", [lbl for _, lbl in zopts]) if zopts else "Todas as Zonas"
        data_fim = st.date_input("Período até", value=None, format="DD/MM/YYYY")
    zona_id = next((zid for zid, lbl in zopts if lbl == zona_label), None) if zopts else None
    df = tarefas_df(
        status=status or None,
        zona_id=zona_id,
        grupo=None if grupo == "Todos" else grupo,
        periodicidade=None if periodicidade == "Todas" else periodicidade,
        data_ini=data_ini,
        data_fim=data_fim,
        limit=5000,
    )
    filtros = {"Status": status or "Todos", "Periodicidade": periodicidade, "Grupo": grupo, "Zona": zona_label, "Período inicial": fmt_data(data_ini), "Período final": fmt_data(data_fim)}
    return df, filtros


def page_relatorios():
    st.header("Relatórios")
    df, filtros = aplicar_filtros_relatorio()
    st.write(f"Registros encontrados: **{len(df)}**")
    st.dataframe(df, use_container_width=True, hide_index=True)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Relatório")
        pd.DataFrame([filtros]).to_excel(writer, index=False, sheet_name="Filtros")
    st.download_button("Baixar Excel", data=buffer.getvalue(), file_name="relatorio_simoc_ba.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if st.button("Gerar PDF simplificado"):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        pdf = BytesIO()
        doc = SimpleDocTemplate(pdf, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elems = [Paragraph("Relatório SIMOC-BA", styles["Title"]), Paragraph("Filtros: " + " | ".join([f"{k}: {v}" for k,v in filtros.items()]), styles["Normal"]), Spacer(1, 12)]
        cols = ["zona", "municipio_sede", "grupo", "atividade", "periodicidade", "prazo", "status", "responsavel_atividade_zona"]
        base = df[[c for c in cols if c in df.columns]].head(80)
        data = [base.columns.tolist()] + base.fillna("").astype(str).values.tolist()
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#174A7C")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 7)]))
        elems.append(tbl)
        doc.build(elems)
        st.download_button("Baixar PDF", data=pdf.getvalue(), file_name="relatorio_simoc_ba.pdf", mime="application/pdf")


def page_orientacoes():
    st.header("Orientações")
    if eh_corregedoria():
        st.write("A Corregedoria deve cadastrar atividades claras, com periodicidade, período de execução, prazo e orientação objetiva para a Zona.")
        st.info("Evite cadastrar atividades duplicadas. Para repetir o acompanhamento, gere um novo checklist com novo período de execução.")
    else:
        st.write("A Zona deve cumprir a atividade, informar o responsável local e enviar o checklist para análise da Corregedoria.")
        st.info("Se a atividade não se aplicar à Zona, marque 'não se aplica' e registre justificativa.")


def page_auditoria():
    st.header("Auditoria")
    st.dataframe(dataframe("select criado_em, usuario_nome, usuario_email, acao, entidade, entidade_id, detalhe from logs_auditoria order by criado_em desc limit 1000"), use_container_width=True, hide_index=True)

# ============================================================
# MAIN
# ============================================================

def main():
    if "user" not in st.session_state:
        login_box()
        return
    if not garantir_banco():
        return
    header()
    pages = nav_pages()
    page = st.radio("Navegação", pages, horizontal=True, label_visibility="collapsed")
    st.divider()
    if page == "Início" and eh_corregedoria():
        page_inicio_corregedoria()
    elif page == "Início" and eh_zona():
        page_inicio_zona()
    elif page == "Atividades":
        page_atividades()
    elif page == "Acompanhamento":
        page_acompanhamento()
    elif page == "Validar":
        page_validacao()
    elif page == "Zonas":
        page_zonas()
    elif page == "Checklist":
        page_checklist_zona()
    elif page == "Orientações":
        page_orientacoes()
    elif page == "Relatórios":
        page_relatorios()
    elif page == "Backup":
        page_backup()
    elif page == "Usuários":
        page_usuarios()
    elif page == "Auditoria":
        page_auditoria()


if __name__ == "__main__":
    main()
