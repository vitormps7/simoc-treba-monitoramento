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
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_DISPONIVEL = True
except Exception:
    plt = None
    MATPLOTLIB_DISPONIVEL = False

from db import db_session, run_schema
from importers import importar_itens_ods
from logo_corregedoria import LOGO_CORREGEDORIA_BASE64
from security import hash_password, verify_password
from treba_importer import importar_zonas, seed_zonas_bahia_padrao, TREBA_CONSULTA_CARTORIOS_URL
from zonas_bahia import ZONAS_BAHIA

st.set_page_config(page_title="SIMOC-BA - Monitoramento Cartorário", page_icon="✅", layout="wide")

FUSO_HORARIO_BRASILIA = timezone(timedelta(hours=-3), name="BRT")
DOMINIO_INSTITUCIONAL = "@tre-ba.jus.br"
NOME_SISTEMA = "SIMOC-BA"
NOME_COMPLETO = "Sistema de Monitoramento Cartorário das Zonas Eleitorais - TRE-BA"
TRIBUNAL_PADRAO = "TRE-BA"
UF_PADRAO = "BA"
UNIDADE_CORREGEDORIA = "CRE-BA"

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
    .main-header {background:linear-gradient(90deg,#EAF3FF,#FFFFFF);padding:16px 20px;border-radius:12px;color:#174A7C;margin-bottom:16px;border:1px solid #D7E0EA;display:flex;align-items:center;gap:18px;}
    .logo-box img {max-width:170px;max-height:64px;object-fit:contain;}
    .main-header h1 {font-size:24px;margin:0 0 4px 0;color:#174A7C;}
    .main-header p {font-size:13px;margin:2px 0;color:#3A5F82;}
    .metric-card {background:white;border:1px solid #D7E0EA;border-top:4px solid #174A7C;border-radius:8px;padding:11px 12px;min-height:94px;text-align:center;}
    .metric-card .label {font-size:12px;font-weight:700;color:#4B5563;margin-bottom:8px;}
    .metric-card .value {font-size:25px;font-weight:800;color:#174A7C;}
    .section-title {background:#174A7C;color:white;padding:8px 11px;border-radius:6px;margin:14px 0 8px 0;font-weight:800;}
    .status-pill {border-radius:999px;padding:3px 9px;color:white;font-weight:700;font-size:12px;display:inline-block;}
    </style>
    """,
    unsafe_allow_html=True,
)


def agora_brasilia() -> datetime:
    return datetime.now(timezone.utc).astimezone(FUSO_HORARIO_BRASILIA).replace(microsecond=0)


def agora_iso() -> str:
    return agora_brasilia().isoformat()


def agora_texto() -> str:
    return agora_brasilia().strftime("%d/%m/%Y %H:%M")


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


# ============================================================
# BANCO, AUDITORIA E DADOS
# ============================================================


def scalar(sql: str, **params):
    with db_session() as conn:
        return conn.execute(text(sql), params).scalar()


def dataframe(sql: str, **params) -> pd.DataFrame:
    with db_session() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


def execute(sql: str, **params):
    with db_session() as conn:
        return conn.execute(text(sql), params)


def registrar_auditoria(acao: str, entidade: str, entidade_id=None, campo: str = "", anterior: str = "", novo: str = "", detalhe: str = ""):
    u = usuario_logado()
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    insert into logs_auditoria
                    (usuario_id, usuario_nome, usuario_email, acao, entidade, entidade_id, campo, valor_anterior, valor_novo, detalhe)
                    values (:uid, :nome, :email, :acao, :entidade, :entidade_id, :campo, :anterior, :novo, :detalhe)
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


def bootstrap_minimo():
    run_schema()
    with db_session() as conn:
        for nome, descricao in PERFIS:
            conn.execute(text("insert into perfis (nome, descricao) values (:nome, :descricao) on conflict (nome) do update set descricao=excluded.descricao"), {"nome": nome, "descricao": descricao})
        # Relação-base no padrão do código anexo: 001 a 205.
        seed_zonas_bahia_padrao(conn)
        admin_email = st.secrets.get("ADMIN_EMAIL", os.getenv("ADMIN_EMAIL", "admin@tre-ba.jus.br"))
        admin_password = st.secrets.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "admin123"))
        perfil_id = conn.execute(text("select id from perfis where nome='admin'")).scalar_one()
        exists = conn.execute(text("select id from usuarios where email=:email"), {"email": normalizar_email(admin_email)}).scalar()
        if not exists:
            conn.execute(
                text("""
                    insert into usuarios (nome, email, senha_hash, perfil_id, ativo, validado, secao_operador)
                    values (:nome, :email, :senha, :perfil_id, true, true, :secao)
                """),
                {"nome": "Administrador", "email": normalizar_email(admin_email), "senha": hash_password(str(admin_password)[:72]), "perfil_id": perfil_id, "secao": UNIDADE_CORREGEDORIA},
            )


def zonas_options(incluir_nenhuma=True) -> list[str]:
    df = dataframe("select id, numero, municipio_sede, uf from zonas_eleitorais where ativa=true order by numero")
    opcoes = ["Nenhuma"] if incluir_nenhuma else []
    if df.empty:
        return opcoes + ZONAS_BAHIA
    for r in df.itertuples():
        sede = r.municipio_sede if r.municipio_sede and r.municipio_sede != "A definir" else "Bahia"
        opcoes.append(f"{int(r.id)} - {int(r.numero):03d}ª ZE - {sede}/{r.uf or 'BA'}")
    return opcoes


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
            conn.execute(text("update usuarios set validado=true, ativo=true, token_validacao=null, atualizado_em=now() where id=:id"), {"id": row["id"]})
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
            text("select id, email from usuarios where token_recuperacao=:token and (token_recuperacao_expira_em is null or token_recuperacao_expira_em > now())"),
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
                conn.execute(text("update usuarios set senha_hash=:h, token_recuperacao=null, token_recuperacao_expira_em=null, atualizado_em=now() where id=:id"), {"h": hash_password(str(nova)[:72]), "id": row["id"]})
            registrar_auditoria("recuperacao_senha", "usuarios", row["id"], detalhe=row["email"])
            st.success("Senha redefinida com sucesso. Faça login novamente.")
    return True


def login_box():
    st.markdown(
        f"""
        <div class="main-header">
            <div class="logo-box"><img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}"></div>
            <div><h1>{NOME_SISTEMA} - {NOME_COMPLETO}</h1><p>Corregedoria Regional Eleitoral da Bahia</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    processar_validacao()
    if processar_recuperacao():
        return

    aba_login, aba_cadastro, aba_recuperar = st.tabs(["Entrar", "Cadastrar usuário", "Recuperar senha"])
    with aba_login:
        with st.form("login"):
            email = normalizar_email(st.text_input("E-mail"))
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
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
                    conn.execute(text("update usuarios set ultimo_login=now() where id=:id"), {"id": row["id"]})
                    st.session_state.user = {k: v for k, v in dict(row).items() if k != "senha_hash"}
                    registrar_auditoria("login", "usuarios", row["id"], detalhe=email)
                    st.rerun()
                elif row and not row["validado"]:
                    st.warning("Cadastro ainda não validado. Verifique o link enviado ao e-mail ou solicite validação ao administrador.")
                else:
                    st.error("Usuário ou senha inválidos.")

    with aba_cadastro:
        st.caption("Cadastro institucional. Novos usuários ficam pendentes de validação quando o e-mail SMTP estiver configurado.")
        with st.form("auto_cadastro"):
            nome = st.text_input("Nome completo")
            email = normalizar_email(st.text_input("E-mail institucional", key="cad_email"))
            zona_label = st.selectbox("Zona vinculada, se for Chefe/Substituto", zonas_options())
            senha = st.text_input("Senha", type="password", key="cad_senha")
            confirmar = st.text_input("Confirmar senha", type="password")
            submitted = st.form_submit_button("Cadastrar")
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

    with aba_recuperar:
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


def cabecalho():
    u = usuario_logado()
    st.markdown(
        f"""
        <div class="main-header">
            <div class="logo-box"><img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}"></div>
            <div><h1>{NOME_SISTEMA} - {NOME_COMPLETO}</h1><p>Corregedoria Regional Eleitoral da Bahia</p><p>Usuário: {u.get('nome','')} | Perfil: {u.get('perfil','')}</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_user():
    st.sidebar.title("Menu")
    st.sidebar.success(f"{usuario_logado().get('nome')}\n\nPerfil: {perfil_atual()}")
    if st.sidebar.button("Sair"):
        registrar_auditoria("logout", "usuarios", usuario_logado().get("id"))
        st.session_state.clear()
        st.rerun()


# ============================================================
# DASHBOARD E MONITORAMENTO
# ============================================================


def render_metric(label, value, color="#174A7C"):
    st.markdown(f"<div class='metric-card' style='border-top-color:{color};'><div class='label'>{label}</div><div class='value' style='color:{color};'>{value}</div></div>", unsafe_allow_html=True)


def atualizar_atrasos():
    with db_session() as conn:
        conn.execute(text("update tarefas_zona set status='atrasado', atualizado_em=now() where prazo < current_date and status='pendente'"))


def page_dashboard():
    atualizar_atrasos()
    st.header("Dashboard gerencial")
    df = dataframe(
        """
        select
          count(*) filter (where status = 'pendente') as pendentes,
          count(*) filter (where status = 'cumprido') as cumpridas,
          count(*) filter (where status = 'cumprido_com_ressalva') as ressalvas,
          count(*) filter (where status = 'atrasado') as atrasadas,
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
        ("Total", total, "#174A7C"), ("Pendentes", int(row["pendentes"]), "#F59E0B"),
        ("Atrasadas", int(row["atrasadas"]), "#B91C1C"), ("Cumpridas", int(row["cumpridas"]), "#2563EB"),
        ("Validadas", int(row["validadas"]), "#15803D"), ("Devolvidas", int(row["devolvidas"]), "#C2410C"),
        ("% validado", f"{conformidade}%", "#7A60A8"),
    ]
    for col, (label, value, color) in zip(cols, cards):
        with col:
            render_metric(label, value, color)

    st.markdown("<div class='section-title'>Zonas com pendências</div>", unsafe_allow_html=True)
    zonas = dataframe(
        """
        select lpad(z.numero::text, 3, '0') || 'ª ZE' as zona, z.municipio_sede,
               count(t.id) filter (where t.status in ('pendente','atrasado','devolvido')) as pendencias,
               count(t.id) filter (where t.status = 'atrasado') as atrasos,
               count(t.id) as total
        from zonas_eleitorais z
        left join tarefas_zona t on t.zona_eleitoral_id = z.id
        group by z.numero, z.municipio_sede
        order by pendencias desc, atrasos desc, z.numero asc
        limit 80
        """
    )
    st.dataframe(zonas, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div class='section-title'>Itens mais pendentes</div>", unsafe_allow_html=True)
        st.dataframe(dataframe("""
            select i.grupo, i.descricao, count(t.id) as pendencias
            from tarefas_zona t join itens_monitoramento i on i.id = t.item_monitoramento_id
            where t.status in ('pendente','atrasado','devolvido')
            group by i.grupo, i.descricao order by pendencias desc limit 30
        """), use_container_width=True, hide_index=True)
    with col2:
        st.markdown("<div class='section-title'>Evolução por ciclo</div>", unsafe_allow_html=True)
        st.dataframe(dataframe("""
            select c.tipo_periodicidade, c.periodo_inicio, c.periodo_fim,
                   count(t.id) as total,
                   count(t.id) filter (where t.status='validado') as validadas,
                   count(t.id) filter (where t.status='atrasado') as atrasadas
            from ciclos_monitoramento c left join tarefas_zona t on t.ciclo_id=c.id
            group by c.id, c.tipo_periodicidade, c.periodo_inicio, c.periodo_fim
            order by c.periodo_inicio desc limit 20
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
    st.header("Gerar tarefas de monitoramento")
    frequencia = st.selectbox("Frequência", ["diaria", "semanal", "quinzenal", "mensal", "bimestral", "trimestral", "anual"])
    inicio = st.date_input("Início", value=date.today().replace(day=1))
    fim = st.date_input("Fim", value=inicio + timedelta(days=30))
    prazo = st.date_input("Prazo de preenchimento", value=fim)
    somente_itens = st.checkbox("Gerar apenas itens ativos desta frequência", value=True)
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
    atualizar_atrasos()
    st.header("Preenchimento do checklist")
    user = usuario_logado()
    filtro_status = st.multiselect("Status", STATUS_TAREFA, default=["pendente", "atrasado", "devolvido"])
    zona_id = user.get("zona_eleitoral_id") if perfil_atual() in ["chefe_cartorio", "substituto"] else None
    tarefas = tarefas_df(filtro_status, zona_id, 500)
    st.dataframe(tarefas, use_container_width=True, hide_index=True)
    if tarefas.empty:
        return
    tarefa_id = st.selectbox("Escolha a tarefa para preencher/comentar", tarefas["id"].tolist())
    with st.expander("Histórico, comentários e anexos da tarefa", expanded=False):
        hist = dataframe("""
            select r.enviado_em as data, u.nome as usuario, r.status, r.observacao, r.justificativa, r.evidencia_url
            from respostas r join usuarios u on u.id=r.usuario_id where r.tarefa_zona_id=:id order by r.enviado_em desc
        """, id=tarefa_id)
        st.dataframe(hist, use_container_width=True, hide_index=True)
        comentarios = dataframe("select criado_em, autor_nome, comentario from comentarios_tarefa where tarefa_zona_id=:id order by criado_em desc", id=tarefa_id)
        st.dataframe(comentarios, use_container_width=True, hide_index=True)
        anexos = dataframe("select criado_em, enviado_por_nome, nome_arquivo, url_arquivo from anexos_tarefa where tarefa_zona_id=:id order by criado_em desc", id=tarefa_id)
        st.dataframe(anexos, use_container_width=True, hide_index=True)
    with st.form("responder"):
        status = st.selectbox("Status do check", ["cumprido", "cumprido_com_ressalva", "nao_se_aplica", "pendente"])
        observacao = st.text_area("Observação")
        justificativa = st.text_area("Justificativa, se houver")
        evidencia_url = st.text_input("URL da evidência/documento SEI, se aplicável")
        comentario = st.text_area("Comentário interno opcional")
        anexo_nome = st.text_input("Nome do anexo/link opcional")
        anexo_url = st.text_input("URL do anexo/link opcional")
        submitted = st.form_submit_button("Enviar check", type="primary")
    if submitted:
        with db_session() as conn:
            conn.execute(text("""
                insert into respostas (tarefa_zona_id, usuario_id, status, observacao, justificativa, evidencia_url)
                values (:tarefa, :usuario, :status, :observacao, :justificativa, :evidencia)
            """), {"tarefa": tarefa_id, "usuario": user["id"], "status": status, "observacao": observacao, "justificativa": justificativa, "evidencia": evidencia_url})
            conn.execute(text("update tarefas_zona set status=:status, atualizado_em=now() where id=:id"), {"status": status, "id": tarefa_id})
            if comentario.strip():
                conn.execute(text("""
                    insert into comentarios_tarefa (tarefa_zona_id, comentario, autor_usuario_id, autor_nome, autor_email)
                    values (:id, :comentario, :uid, :nome, :email)
                """), {"id": tarefa_id, "comentario": comentario.strip(), "uid": user["id"], "nome": user["nome"], "email": user["email"]})
            if anexo_url.strip():
                conn.execute(text("""
                    insert into anexos_tarefa (tarefa_zona_id, nome_arquivo, url_arquivo, enviado_por_usuario_id, enviado_por_nome, enviado_por_email)
                    values (:id, :nome_arq, :url, :uid, :nome, :email)
                """), {"id": tarefa_id, "nome_arq": anexo_nome or "Link de evidência", "url": anexo_url, "uid": user["id"], "nome": user["nome"], "email": user["email"]})
        registrar_auditoria("enviar_check", "tarefas_zona", tarefa_id, campo="status", novo=status)
        st.success("Check enviado para acompanhamento da Corregedoria.")
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
            conn.execute(text("update tarefas_zona set status=:status, observacao_corregedoria=:obs, atualizado_em=now() where id=:id"), {"status": acao, "obs": obs, "id": tarefa_id})
        registrar_auditoria("validar_check", "tarefas_zona", tarefa_id, campo="status", novo=acao, detalhe=obs)
        st.success("Validação registrada.")
        st.rerun()


# ============================================================
# IMPORTAÇÃO, USUÁRIOS, BACKUP E RELATÓRIOS
# ============================================================


def page_importacao():
    st.header("Carga inicial e importações")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Criar/atualizar schema"):
        run_schema(); st.success("Schema verificado/criado no Supabase.")
    if c2.button("Importar consulta pública TRE-BA"):
        with db_session() as conn:
            base = seed_zonas_bahia_padrao(conn)
            total = importar_zonas(conn)
        registrar_auditoria("importar_zonas", "zonas_eleitorais", detalhe=TREBA_CONSULTA_CARTORIOS_URL)
        st.success(f"Relação-base garantida ({base} zonas) e {total} zonas atualizadas pela consulta pública: {TREBA_CONSULTA_CARTORIOS_URL}")
    if c3.button("Garantir zonas 001-205"):
        with db_session() as conn:
            total = seed_zonas_bahia_padrao(conn)
        st.success(f"{total} zonas da relação-base 001 a 205 foram verificadas.")
    if c4.button("Importar planilha padrão"):
        ods = Path(__file__).parent / "PLANO DE AÇÃO - MONITORAMENTO CARTORÁRIO.ods"
        with db_session() as conn:
            total = importar_itens_ods(conn, ods)
        registrar_auditoria("importar_planilha", "itens_monitoramento", detalhe=str(ods))
        st.success(f"{total} itens de monitoramento processados a partir da planilha.")

    uploaded = st.file_uploader("Importar outra planilha ODS", type=["ods"])
    if uploaded and st.button("Importar arquivo enviado"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ods") as tmp:
            tmp.write(uploaded.getbuffer()); tmp_path = tmp.name
        with db_session() as conn:
            total = importar_itens_ods(conn, tmp_path)
        os.unlink(tmp_path)
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
                        values (:nome, :email, :cpf, :senha, :perfil, :zona, :ativo, :validado, :secao, now())
                        on conflict (email) do update set nome=excluded.nome, cpf=excluded.cpf, senha_hash=excluded.senha_hash, perfil_id=excluded.perfil_id, zona_eleitoral_id=excluded.zona_eleitoral_id, ativo=excluded.ativo, validado=excluded.validado, atualizado_em=now()
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
                execute("update usuarios set validado=true, ativo=true, token_validacao=null, atualizado_em=now() where id=:id", id=int(uid))
                registrar_auditoria("validar_usuario_admin", "usuarios", int(uid)); st.success("Usuário validado.")
            if col2.button("Desativar/ativar"):
                execute("update usuarios set ativo=not ativo, atualizado_em=now() where id=:id", id=int(uid))
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
        data_de = st.date_input("Prazo de", value=None)
        data_ate = st.date_input("Prazo até", value=None)
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


def page_auditoria():
    st.header("Auditoria e histórico")
    st.dataframe(dataframe("select criado_em, usuario_nome, usuario_email, acao, entidade, entidade_id, campo, valor_anterior, valor_novo, detalhe from logs_auditoria order by criado_em desc limit 500"), use_container_width=True, hide_index=True)


def main():
    try:
        bootstrap_minimo()
    except Exception as exc:
        st.error("Não foi possível conectar/criar o banco. Confira DATABASE_URL nos Secrets do Streamlit/Supabase.")
        st.exception(exc)
        return
    if "user" not in st.session_state:
        login_box()
        return
    cabecalho()
    sidebar_user()
    perfil = perfil_atual()
    pages = ["Dashboard", "Zonas", "Minhas tarefas"]
    if eh_corregedoria():
        pages += ["Validação", "Gerar tarefas", "Relatórios"]
    if perfil == "auditor":
        pages += ["Relatórios"]
    if perfil == "admin":
        pages += ["Importação", "Usuários", "Backup e restauração", "Auditoria"]
    page = st.sidebar.radio("Navegação", pages)
    if page == "Dashboard": page_dashboard()
    elif page == "Zonas": page_zonas()
    elif page == "Minhas tarefas": page_minhas_tarefas()
    elif page == "Validação": page_validacao()
    elif page == "Gerar tarefas": page_gerar_tarefas()
    elif page == "Importação": page_importacao()
    elif page == "Usuários": page_usuarios()
    elif page == "Backup e restauração": page_backup()
    elif page == "Relatórios": page_relatorios()
    elif page == "Auditoria": page_auditoria()


if __name__ == "__main__":
    main()
