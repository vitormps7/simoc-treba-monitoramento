from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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

FUSO_HORARIO_BRASILIA = timezone(timedelta(hours=-3), name="BRT")
FORMATO_DATA = "%d/%m/%Y"
FORMATO_DATA_HORA = "%d/%m/%Y %H:%M"
NOME_SISTEMA = "SIMOC-BA"
DOMINIO_INSTITUCIONAL = "@tre-ba.jus.br"
UNIDADE_CORREGEDORIA = "CRE-BA"
PERFIS = [
    ("admin", "Administrador do sistema"),
    ("corregedoria_gestor", "Corregedoria - gestor"),
    ("corregedoria_analista", "Corregedoria - analista"),
    ("chefe_cartorio", "Zona Eleitoral - chefe de cartório"),
    ("substituto", "Zona Eleitoral - substituto"),
    ("auditor", "Auditoria/consulta"),
]
STATUS_ZONA = ["cumprido", "cumprido_com_ressalva", "nao_se_aplica", "pendente"]
STATUS_TAREFA = ["pendente", "atrasado", "em_analise", "validado", "devolvido", "cumprido", "cumprido_com_ressalva", "nao_se_aplica"]
PERIODICIDADES = ["diariamente", "semanalmente", "quinzenalmente", "mensalmente", "bimestralmente", "trimestralmente", "anualmente", "por demanda"]

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none !important; visibility:hidden !important; width:0 !important;}
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
    </style>
    """,
    unsafe_allow_html=True,
)


def agora_brasilia() -> datetime:
    return datetime.now(timezone.utc).astimezone(FUSO_HORARIO_BRASILIA).replace(microsecond=0)


def fmt_data(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    if isinstance(valor, datetime):
        return valor.strftime(FORMATO_DATA_HORA)
    if isinstance(valor, date):
        return valor.strftime(FORMATO_DATA)
    try:
        return pd.to_datetime(valor).strftime(FORMATO_DATA_HORA if ":" in str(valor) else FORMATO_DATA)
    except Exception:
        return str(valor)


def dataframe(sql: str, **params) -> pd.DataFrame:
    with db_session() as conn:
        df = pd.read_sql_query(text(sql), conn, params=params)
    for col in df.columns:
        if any(x in col for x in ["data", "prazo", "periodo", "criado", "atualizado", "enviado", "validado", "login"]):
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


def garantir_banco():
    try:
        preparar_banco_once()
        return True
    except Exception as e:
        st.error(f"Não foi possível conectar ao banco: {e}")
        return False


def perfil_atual() -> str:
    return st.session_state.get("user", {}).get("perfil", "")


def usuario_logado() -> dict:
    return st.session_state.get("user", {})


def eh_corregedoria() -> bool:
    return perfil_atual() in ["admin", "corregedoria_gestor", "corregedoria_analista"]


def eh_zona() -> bool:
    return perfil_atual() in ["chefe_cartorio", "substituto"]


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


def header():
    u = usuario_logado()
    st.markdown(f"""
    <div class="main-header">
        <img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}">
        <div>
            <h1>SIMOC-BA - Monitoramento Cartorário</h1>
            <p>Corregedoria Regional Eleitoral da Bahia | Controle de atividades, periodicidade e checklist das Zonas</p>
            <p>Usuário: <b>{u.get('nome','')}</b> · Perfil: <b>{u.get('perfil','')}</b></p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    col1, col2 = st.columns([5,1])
    with col2:
        if st.button("Sair", use_container_width=True):
            registrar_auditoria("logout", "usuarios", u.get("id"))
            st.session_state.clear()
            st.rerun()


def login_box():
    st.markdown(f"""
    <div class="auth-hero">
        <div class="auth-logo-band"><img src="data:image/png;base64,{LOGO_CORREGEDORIA_BASE64}"></div>
        <div class="auth-title">SIMOC-BA - Sistema de Monitoramento Cartorário</div>
        <div class="auth-subtitle">Corregedoria cadastra as atividades; Zona executa e marca o checklist para validação.</div>
    </div>
    """, unsafe_allow_html=True)
    tab = st.radio("Acesso", ["Entrar", "Cadastrar usuário"], horizontal=True)
    if tab == "Entrar":
        with st.form("login"):
            email = st.text_input("E-mail").strip().lower()
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
            if not garantir_banco():
                return
            with db_session() as conn:
                row = conn.execute(text("""
                    select u.id, u.nome, u.email, u.senha_hash, u.zona_eleitoral_id, p.nome as perfil, u.validado
                    from usuarios u join perfis p on p.id=u.perfil_id
                    where u.email=:email and u.ativo=true
                """), {"email": email}).mappings().first()
                if row and row["validado"] and verify_password(senha, row["senha_hash"]):
                    conn.execute(text("update usuarios set ultimo_login=(now() at time zone 'America/Sao_Paulo') where id=:id"), {"id": row["id"]})
                    st.session_state.user = {k:v for k,v in dict(row).items() if k != "senha_hash"}
                    registrar_auditoria("login", "usuarios", row["id"], email)
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
    else:
        st.info("O cadastro de usuários de Zona deve ser vinculado pela Corregedoria a uma Zona Eleitoral.")
        with st.form("cadastro"):
            nome = st.text_input("Nome completo")
            email = st.text_input("E-mail institucional").strip().lower()
            senha = st.text_input("Senha", type="password")
            confirmar = st.text_input("Confirmar senha", type="password")
            submitted = st.form_submit_button("Solicitar cadastro")
        if submitted:
            if not garantir_banco():
                return
            if not nome or not email.endswith(DOMINIO_INSTITUCIONAL) or len(senha) < 6 or senha != confirmar:
                st.warning("Confira nome, e-mail institucional e senha.")
            else:
                with db_session() as conn:
                    perfil = conn.execute(text("select id from perfis where nome='chefe_cartorio'")).scalar_one()
                    conn.execute(text("""
                        insert into usuarios (nome,email,senha_hash,perfil_id,ativo,validado,secao_operador)
                        values (:n,:e,:s,:p,true,false,:secao)
                        on conflict (email) do nothing
                    """), {"n": nome, "e": email, "s": hash_password(senha), "p": perfil, "secao": UNIDADE_CORREGEDORIA})
                st.success("Cadastro solicitado. A Corregedoria deve validar e vincular a Zona.")


def metric(label, value):
    st.markdown(f"<div class='metric-card'><div class='label'>{label}</div><div class='value'>{value}</div></div>", unsafe_allow_html=True)


def page_inicio_corregedoria():
    st.markdown("""
    <div class='banner corregedoria'><h2>Interface da Corregedoria</h2>
    <p><b>Fluxo:</b> cadastrar atividade monitorada → definir periodicidade/período/prazo → gerar checklist para as Zonas → acompanhar realização → validar ou devolver.</p></div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='step-flow'><span>1. Cadastrar atividade</span><span>2. Definir periodicidade</span><span>3. Gerar checklist</span><span>4. Zona marca realização</span><span>5. Corregedoria valida</span></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        metric("Atividades ativas", dataframe("select count(*) as total from itens_monitoramento where ativo=true").iloc[0,0])
    with col2:
        metric("Tarefas pendentes", dataframe("select count(*) as total from tarefas_zona where status in ('pendente','atrasado','devolvido')").iloc[0,0])
    with col3:
        metric("Para validar", dataframe("select count(*) as total from tarefas_zona where status='em_analise'").iloc[0,0])
    st.caption("Use a navegação acima. Não há menu lateral.")


def page_inicio_zona():
    st.markdown("""
    <div class='banner zona'><h2>Interface da Zona Eleitoral</h2>
    <p>A Zona visualiza somente as atividades que a Corregedoria gerou para ela, informa o responsável local e marca o checklist de realização.</p></div>
    """, unsafe_allow_html=True)
    z = usuario_logado().get("zona_eleitoral_id")
    if z:
        df = dataframe("select lpad(numero::text,3,'0') as zona, municipio_sede from zonas_eleitorais where id=:id", id=z)
        if not df.empty:
            st.success(f"Zona vinculada: {df.iloc[0]['zona']}ª ZE - {df.iloc[0]['municipio_sede']}/BA")
    col1, col2 = st.columns(2)
    with col1:
        metric("Checklist pendente", dataframe("select count(*) as total from tarefas_zona where zona_eleitoral_id=:z and status in ('pendente','atrasado','devolvido')", z=z or -1).iloc[0,0])
    with col2:
        metric("Enviado à Corregedoria", dataframe("select count(*) as total from tarefas_zona where zona_eleitoral_id=:z and status='em_analise'", z=z or -1).iloc[0,0])


def page_atividades():
    st.header("Atividades monitoradas e geração de checklist")
    st.info("Esta é a tela principal da Corregedoria: aqui a atividade é cadastrada, recebe periodicidade/período/prazo e é distribuída às Zonas.")
    with st.form("atividade"):
        c1, c2 = st.columns(2)
        with c1:
            grupo = st.selectbox("Grupo da atividade", ["ELO", "SISTEMAS DA INTRANET", "OBSERVAÇÕES", "OUTROS"])
            descricao = st.text_area("Atividade a ser monitorada", placeholder="Ex.: RAE em diligência; Banco de Erros; PJe; Diário DJE...")
            periodicidade = st.selectbox("Periodicidade de acompanhamento", PERIODICIDADES)
            responsavel_ref = st.text_input("Responsável de referência da planilha/orientação", placeholder="Ex.: Emerson e Rosy; Todos os atendentes")
        with c2:
            inicio = st.date_input("Início do período de execução", value=date.today().replace(day=1), format="DD/MM/YYYY")
            fim = st.date_input("Fim do período de execução", value=date.today(), format="DD/MM/YYYY")
            prazo = st.date_input("Prazo para a Zona preencher", value=date.today(), format="DD/MM/YYYY")
            exige_evidencia = st.checkbox("Exigir evidência/link SEI", value=False)
            orientacao = st.text_area("Orientação da Corregedoria para a Zona")
        colg1, colg2 = st.columns(2)
        with colg1:
            destino = st.radio("Destino", ["Todas as Zonas ativas", "Uma Zona específica"], horizontal=True)
        with colg2:
            zona_destino = None
            if destino == "Uma Zona específica":
                zonas = dataframe("select id, lpad(numero::text,3,'0') || 'ª ZE - ' || coalesce(municipio_sede,'A definir') || '/BA' as label from zonas_eleitorais where ativa=true order by numero")
                if zonas.empty:
                    st.warning("Não há zonas cadastradas. Use a tela Zonas Eleitorais para carregar a base.")
                else:
                    label = st.selectbox("Zona", zonas["label"].tolist())
                    zona_destino = int(zonas.loc[zonas["label"] == label, "id"].iloc[0])
        submitted = st.form_submit_button("Salvar atividade e gerar checklist", type="primary")
    if submitted:
        if not descricao.strip():
            st.warning("Informe a atividade.")
            return
        if fim < inicio or prazo < inicio:
            st.warning("Confira período e prazo.")
            return
        with db_session() as conn:
            item_id = conn.execute(text("""
                insert into itens_monitoramento (grupo, descricao, responsavel_origem, frequencia, exige_evidencia, criticidade, ativo, orientacao_corregedoria, prazo_padrao_dias, atualizado_em)
                values (:grupo,:descricao,:resp,:freq,:evid,'media',true,:orientacao,0,(now() at time zone 'America/Sao_Paulo'))
                on conflict (grupo, descricao) do update set responsavel_origem=excluded.responsavel_origem, frequencia=excluded.frequencia, exige_evidencia=excluded.exige_evidencia, orientacao_corregedoria=excluded.orientacao_corregedoria, ativo=true, atualizado_em=(now() at time zone 'America/Sao_Paulo')
                returning id
            """), {"grupo": grupo, "descricao": descricao.strip(), "resp": responsavel_ref.strip() or None, "freq": periodicidade, "evid": exige_evidencia, "orientacao": orientacao.strip() or None}).scalar_one()
            ciclo_id = conn.execute(text("""
                insert into ciclos_monitoramento (periodo_inicio, periodo_fim, tipo_periodicidade, status)
                values (:inicio,:fim,:freq,'aberto')
                on conflict (periodo_inicio, periodo_fim, tipo_periodicidade) do update set status='aberto'
                returning id
            """), {"inicio": inicio, "fim": fim, "freq": periodicidade}).scalar_one()
            if zona_destino:
                conn.execute(text("""
                    insert into tarefas_zona (zona_eleitoral_id,item_monitoramento_id,ciclo_id,prazo,status)
                    values (:zona,:item,:ciclo,:prazo,'pendente')
                    on conflict (zona_eleitoral_id,item_monitoramento_id,ciclo_id) do nothing
                """), {"zona": zona_destino, "item": item_id, "ciclo": ciclo_id, "prazo": prazo})
                detalhe = f"1 zona - {descricao}"
            else:
                conn.execute(text("""
                    insert into tarefas_zona (zona_eleitoral_id,item_monitoramento_id,ciclo_id,prazo,status)
                    select id, :item, :ciclo, :prazo, 'pendente' from zonas_eleitorais where ativa=true
                    on conflict (zona_eleitoral_id,item_monitoramento_id,ciclo_id) do nothing
                """), {"item": item_id, "ciclo": ciclo_id, "prazo": prazo})
                detalhe = f"todas as zonas - {descricao}"
        registrar_auditoria("salvar_atividade_gerar_checklist", "itens_monitoramento", item_id, detalhe)
        st.success("Atividade salva e checklist gerado. Tarefas existentes foram preservadas; nenhum dado foi apagado.")
        st.cache_data.clear()
    st.subheader("Atividades cadastradas")
    st.dataframe(dataframe("""
        select grupo, descricao, responsavel_origem as responsavel_referencia, frequencia as periodicidade, exige_evidencia, ativo, orientacao_corregedoria
        from itens_monitoramento order by grupo, descricao
    """), use_container_width=True, hide_index=True)


def tarefas_df(zona_id=None, status=None, limit=500):
    where = ["1=1"]
    params = {"limit": limit}
    if zona_id:
        where.append("t.zona_eleitoral_id=:zona")
        params["zona"] = zona_id
    if status:
        where.append("t.status = any(:status)")
        params["status"] = status
    return dataframe(f"""
        select t.id, lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.municipio_sede, i.grupo, i.descricao,
               i.frequencia as periodicidade, i.responsavel_origem as responsavel_referencia,
               t.responsavel_atividade_zona as responsavel_na_zona, t.data_execucao,
               c.periodo_inicio, c.periodo_fim, t.prazo, t.status, i.exige_evidencia, i.orientacao_corregedoria
        from tarefas_zona t
        join zonas_eleitorais z on z.id=t.zona_eleitoral_id
        join itens_monitoramento i on i.id=t.item_monitoramento_id
        join ciclos_monitoramento c on c.id=t.ciclo_id
        where {' and '.join(where)}
        order by t.prazo asc, z.numero asc, i.grupo asc
        limit :limit
    """, **params)


def page_checklist_zona():
    st.header("Checklist da Zona")
    user = usuario_logado()
    zona_id = user.get("zona_eleitoral_id")
    if not zona_id:
        st.error("Seu usuário ainda não está vinculado a uma Zona Eleitoral. Peça à Corregedoria para vincular seu cadastro.")
        return
    filtro = st.multiselect("Status", STATUS_TAREFA, default=["pendente", "atrasado", "devolvido"])
    tarefas = tarefas_df(zona_id=zona_id, status=filtro, limit=300)
    st.dataframe(tarefas, use_container_width=True, hide_index=True)
    if tarefas.empty:
        st.success("Não há tarefas para o filtro selecionado.")
        return
    st.subheader("Marcar realização")
    tarefa_id = st.selectbox("Atividade", tarefas["id"].tolist(), format_func=lambda x: f"#{x} - {tarefas.loc[tarefas['id']==x, 'descricao'].iloc[0]}")
    tarefa = tarefas[tarefas["id"] == tarefa_id].iloc[0]
    st.info(f"Atividade: {tarefa['descricao']} | Periodicidade: {tarefa['periodicidade']} | Prazo: {tarefa['prazo']} | Orientação: {tarefa.get('orientacao_corregedoria') or 'Sem orientação específica.'}")
    with st.form("check"):
        responsavel = st.text_input("Responsável pela atividade na Zona", value=str(tarefa.get("responsavel_na_zona") or ""))
        data_exec = st.date_input("Data de execução/conferência", value=date.today(), format="DD/MM/YYYY")
        status = st.radio("Resultado do checklist", STATUS_ZONA, horizontal=True)
        obs = st.text_area("Observação da Zona")
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
            """), {"tarefa": int(tarefa_id), "usuario": user["id"], "status": status, "obs": obs, "just": justificativa, "evid": evidencia})
            novo = "em_analise" if status in ["cumprido", "cumprido_com_ressalva", "nao_se_aplica"] else "pendente"
            conn.execute(text("""
                update tarefas_zona set status=:status, responsavel_atividade_zona=:resp, data_execucao=:data_exec, atualizado_em=(now() at time zone 'America/Sao_Paulo') where id=:id
            """), {"status": novo, "resp": responsavel.strip(), "data_exec": data_exec, "id": int(tarefa_id)})
        registrar_auditoria("zona_marca_checklist", "tarefas_zona", int(tarefa_id), f"{status} - {responsavel}")
        st.success("Checklist enviado para visualização/validação da Corregedoria.")
        st.rerun()


def page_acompanhamento():
    st.header("Acompanhamento da realização pelas Zonas")
    c1, c2 = st.columns([2,1])
    with c1:
        status = st.multiselect("Status", STATUS_TAREFA, default=["pendente", "atrasado", "em_analise", "devolvido"])
    with c2:
        limite = st.number_input("Limite", 50, 2000, 500, 50)
    df = tarefas_df(status=status, limit=int(limite))
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_validacao():
    st.header("Validar checklist enviado pela Zona")
    df = dataframe("""
        select distinct on (r.tarefa_zona_id) r.id as resposta_id, t.id as tarefa_id,
               lpad(z.numero::text,3,'0') || 'ª ZE' as zona, z.municipio_sede, i.grupo, i.descricao,
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
    resposta_id = st.selectbox("Resposta", df["resposta_id"].tolist())
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
    filtro = st.text_input("Filtrar")
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
            email = st.text_input("E-mail").strip().lower()
            senha = st.text_input("Senha inicial", type="password")
        with c2:
            perfil = st.selectbox("Perfil", [p[0] for p in PERFIS])
            ativo = st.checkbox("Ativo", value=True)
            validado = st.checkbox("Validado", value=True)
        with c3:
            zonas = dataframe("select id, lpad(numero::text,3,'0') || 'ª ZE - ' || coalesce(municipio_sede,'A definir') || '/BA' as label from zonas_eleitorais order by numero")
            zona_id = None
            if not zonas.empty:
                label = st.selectbox("Zona vinculada, se perfil de Zona", ["Sem zona"] + zonas["label"].tolist())
                if label != "Sem zona":
                    zona_id = int(zonas.loc[zonas["label"] == label, "id"].iloc[0])
        salvar = st.form_submit_button("Salvar usuário", type="primary")
    if salvar:
        if not nome or not email:
            st.warning("Informe nome e e-mail.")
            return
        with db_session() as conn:
            perfil_id = conn.execute(text("select id from perfis where nome=:p"), {"p": perfil}).scalar_one()
            existe = conn.execute(text("select id from usuarios where email=:e"), {"e": email}).scalar()
            if existe:
                conn.execute(text("""
                    update usuarios set nome=:n, perfil_id=:p, zona_eleitoral_id=:z, ativo=:a, validado=:v, atualizado_em=(now() at time zone 'America/Sao_Paulo') where email=:e
                """), {"n": nome, "p": perfil_id, "z": zona_id, "a": ativo, "v": validado, "e": email})
            else:
                if not senha:
                    st.warning("Informe senha inicial para novo usuário.")
                    return
                conn.execute(text("""
                    insert into usuarios (nome,email,senha_hash,perfil_id,zona_eleitoral_id,ativo,validado,secao_operador)
                    values (:n,:e,:s,:p,:z,:a,:v,:secao)
                """), {"n": nome, "e": email, "s": hash_password(senha), "p": perfil_id, "z": zona_id, "a": ativo, "v": validado, "secao": UNIDADE_CORREGEDORIA})
        st.success("Usuário salvo.")
    st.dataframe(dataframe("""
        select u.nome, u.email, p.nome as perfil, lpad(z.numero::text,3,'0') || 'ª ZE - ' || coalesce(z.municipio_sede,'A definir') as zona, u.ativo, u.validado, u.ultimo_login
        from usuarios u join perfis p on p.id=u.perfil_id left join zonas_eleitorais z on z.id=u.zona_eleitoral_id
        order by p.nome, u.nome
    """), use_container_width=True, hide_index=True)


def page_orientacoes():
    st.header("Orientações")
    if eh_corregedoria():
        st.write("A Corregedoria deve cadastrar atividades claras, com periodicidade, período de execução, prazo e orientação objetiva para a Zona.")
    else:
        st.write("A Zona deve cumprir a atividade, informar o responsável local e enviar o checklist para análise da Corregedoria.")


def page_auditoria():
    st.header("Auditoria")
    st.dataframe(dataframe("select criado_em, usuario_nome, acao, entidade, entidade_id, detalhe from logs_auditoria order by criado_em desc limit 500"), use_container_width=True, hide_index=True)


def main():
    if "user" not in st.session_state:
        login_box()
        return
    if not garantir_banco():
        return
    header()
    if eh_corregedoria():
        pages = ["Início", "Atividades e checklist", "Acompanhamento", "Validar", "Zonas Eleitorais", "Usuários", "Auditoria"]
    elif eh_zona():
        pages = ["Início", "Checklist da Zona", "Orientações"]
    else:
        pages = ["Acompanhamento", "Zonas Eleitorais"]
    page = st.radio("Navegação", pages, horizontal=True, label_visibility="collapsed")
    st.divider()
    if page == "Início" and eh_corregedoria():
        page_inicio_corregedoria()
    elif page == "Início" and eh_zona():
        page_inicio_zona()
    elif page == "Atividades e checklist":
        page_atividades()
    elif page == "Acompanhamento":
        page_acompanhamento()
    elif page == "Validar":
        page_validacao()
    elif page == "Zonas Eleitorais":
        page_zonas()
    elif page == "Checklist da Zona":
        page_checklist_zona()
    elif page == "Usuários":
        page_usuarios()
    elif page == "Auditoria":
        page_auditoria()
    elif page == "Orientações":
        page_orientacoes()


if __name__ == "__main__":
    main()
