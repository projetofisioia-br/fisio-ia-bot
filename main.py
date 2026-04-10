# =================================================================
# BLOCO 1 - IMPORTS, CONFIGURAÇÕES, BANCO E BUSCAS
# =================================================================

import subprocess
import sys

def instalar_pacotes():
    pacotes = [
        "pymed",
        "requests",
        "beautifulsoup4",
        "pytesseract",
        "pillow",
        "telebot",
        "flask",
        "pymongo",
        "reportlab"
    ]
    for pacote in pacotes:
        try:
            __import__(pacote.replace("-", "_"))
        except ImportError:
            print(f"[STARTUP] Instalando {pacote}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pacote])

instalar_pacotes()

import os
import io
import time
import threading
import random
import string
import logging
import secrets
from datetime import datetime, timedelta

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

import pytesseract
from PIL import Image
import requests
import telebot
from telebot import types
from flask import Flask, render_template_string, request
from pymongo import MongoClient
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_JUSTIFY

# ================= CONFIGURAÇÕES =================
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
DOMAIN = os.environ.get("DOMAIN", "https://fisio-ia-bot-1.onrender.com").strip()
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

if not TOKEN_TELEGRAM:
    raise ValueError("TOKEN_TELEGRAM não definido")
if not MONGO_URI:
    raise ValueError("MONGO_URI não definido")
if not API_KEY_IA:
    raise ValueError("API_KEY_IA não definido")
if not SECRET_KEY:
    logger.warning("SECRET_KEY não definido – usando chave gerada aleatoriamente (sessões Flask serão resetadas a cada reinício)")

# ================= BANCO DE DADOS =================
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=30000
)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
uso_coll = db['uso_usuarios']
logs_coll = db['logs_analises']
tokens_coll = db['dashboard_tokens']

def criar_indices():
    try:
        pacientes_coll.create_index("profissional_id")
        uso_coll.create_index("user_id", unique=True)
        uso_coll.create_index("codigo_indicacao")
        logs_coll.create_index("user_id")
        tokens_coll.create_index("token", unique=True)
        tokens_coll.create_index("expira_em", expireAfterSeconds=0)
        logger.info("Índices MongoDB criados/verificados com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao criar índices MongoDB: {e}")

criar_indices()

# ================= FUNÇÕES AUXILIARES =================
def is_admin(user_id):
    return user_id == ADMIN_ID

def gerar_codigo_indicacao():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def registrar_usuario_se_novo(user_id, codigo_indicador=None):
    if is_admin(user_id):
        return
    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        if codigo_indicador:
            indicador = uso_coll.find_one({"codigo_indicacao": codigo_indicador})
            if indicador and indicador["user_id"] != user_id:
                novo_credito = min(indicador.get("creditos_desconto", 0) + 25, 50)
                uso_coll.update_one({"_id": indicador["_id"]}, {"$set": {"creditos_desconto": novo_credito}})
                uso_coll.update_one({"_id": indicador["_id"]}, {"$push": {"indicacoes": {"user_id": user_id, "data": datetime.now()}}})
                try:
                    bot.send_message(indicador["user_id"], f"🎉 Parabéns! Um novo profissional se cadastrou usando seu código. Você ganhou +25% de desconto na próxima mensalidade! Seu saldo atual: {novo_credito}%")
                except Exception as e:
                    logger.warning(f"Não foi possível notificar indicador {indicador['user_id']}: {e}")

        uso_coll.insert_one({
            "user_id": user_id,
            "uso": 0,
            "uso_buscas": 0,
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "pro": False,
            "plano": "gratuito",
            "nome_profissional": "",
            "registro_profissional": "",
            "codigo_indicacao": gerar_codigo_indicacao(),
            "indicacoes": [],
            "creditos_desconto": 0
        })
        if ADMIN_ID:
            try:
                bot.send_message(ADMIN_ID, f"🚀 Novo usuário: ID {user_id}")
            except Exception as e:
                logger.warning(f"Não foi possível notificar admin sobre novo usuário: {e}")

def verificar_assinatura(user):
    if user.get("pro"):
        expira = user.get("pro_expira_em", 0)
        if time.time() > expira:
            uso_coll.update_one({"_id": user["_id"]}, {"$set": {"pro": False, "plano": "gratuito"}})
            return False
        return True
    return False

def obter_limites_plano(plano):
    planos = {
        "gratuito": {"analises": 5, "laudos": 3, "pacientes": 10, "buscas": 5},
        "prata": {"analises": 30, "laudos": 30, "pacientes": 100, "buscas": 30},
        "ouro": {"analises": 60, "laudos": 60, "pacientes": 300, "buscas": 60},
        "diamante": {"analises": 300, "laudos": 300, "pacientes": 1000, "buscas": 300}
    }
    return planos.get(plano, planos["gratuito"])

def pode_usar_recurso(user_id, recurso):
    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        registrar_usuario_se_novo(user_id)
        user = uso_coll.find_one({"user_id": user_id})

    plano = user.get("plano", "gratuito") if user.get("pro") else "gratuito"
    limites = obter_limites_plano(plano)

    hoje = datetime.now()
    ultimo_reset = user.get("ultimo_reset")
    if not ultimo_reset or hoje > ultimo_reset + timedelta(days=30):
        uso_coll.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "uso_mes": 0,
                "laudos_mes": 0,
                "uso_buscas": 0,
                "ultimo_reset": hoje
            }}
        )
        user["uso_mes"] = 0
        user["laudos_mes"] = 0
        user["uso_buscas"] = 0

    if recurso == "analise":
        if user.get("uso_mes", 0) >= limites["analises"]:
            return False
        uso_coll.update_one({"_id": user["_id"]}, {"$inc": {"uso_mes": 1}})
    elif recurso == "laudo":
        if user.get("laudos_mes", 0) >= limites["laudos"]:
            return False
        uso_coll.update_one({"_id": user["_id"]}, {"$inc": {"laudos_mes": 1}})
    elif recurso == "busca":
        if user.get("uso_buscas", 0) >= limites["buscas"]:
            return False
        uso_coll.update_one({"_id": user["_id"]}, {"$inc": {"uso_buscas": 1}})
    return True

def pode_usar(user_id):
    return pode_usar_recurso(user_id, "analise")

MAX_FILE_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_INPUT_LEN = 3000               # caracteres por mensagem de texto

def extrair_texto_arquivo(file_bytes):
    if len(file_bytes) > MAX_FILE_SIZE:
        return None  # sinaliza arquivo muito grande
    try:
        imagem = Image.open(io.BytesIO(file_bytes))
        texto = pytesseract.image_to_string(imagem, lang='por')
        return texto.strip()
    except Exception as e:
        logger.error(f"Erro OCR: {e}")
        return f"Erro OCR: {str(e)}"

def montar_memoria_clinica(paciente):
    memoria = ""
    if paciente.get("ultima_analise"):
        memoria += f"\nÚltima análise:\n{paciente['ultima_analise'][:800]}"
    if paciente.get("evolucao"):
        memoria += f"\nEvolução:\n{paciente['evolucao'][-800:]}"
    if paciente.get("registros_clinicos"):
        memoria += "\nRegistros adicionais:\n"
        for r in paciente.get("registros_clinicos", [])[-5:]:
            data = r.get("data", "")
            info = r.get("info", "")
            memoria += f"- ({data}) {info}\n"
    return memoria.strip()

def gerar_pdf(nome_paciente, texto_analise):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    estilo_corpo = ParagraphStyle(
        'Justify',
        parent=styles['Normal'],
        alignment=TA_JUSTIFY,
        fontSize=11,
        leading=14
    )
    elementos = []
    elementos.append(Paragraph(f"<b>MESTREFISIO PhD - RESUMO CLÍNICO</b>", styles['Title']))
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(f"<b>PACIENTE:</b> {nome_paciente.upper()}", styles['Normal']))
    elementos.append(Paragraph(f"<b>DATA DA EMISSÃO:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elementos.append(Spacer(1, 20))
    for linha in texto_analise.split('\n'):
        if linha.strip():
            elementos.append(Paragraph(linha, estilo_corpo))
            elementos.append(Spacer(1, 8))
    doc.build(elementos)
    buffer.seek(0)
    return buffer

# ================= BUSCAS CIENTÍFICAS =================
from pymed import PubMed
import urllib.parse

pubmed = PubMed(tool="MestreFisio", email="pesquisador@exemplo.com")

def buscar_pubmed(query, max_results=3):
    try:
        resultados = pubmed.query(query, max_results=max_results)
        artigos = []
        for artigo in resultados:
            if artigo.abstract:
                artigos.append({
                    "fonte": "PubMed",
                    "titulo": artigo.title,
                    "resumo": artigo.abstract[:800],
                    "link": f"https://pubmed.ncbi.nlm.nih.gov/{artigo.pubmed_id}/" if artigo.pubmed_id else ""
                })
        return artigos
    except Exception as e:
        logger.error(f"Erro PubMed: {e}")
        return []

def buscar_scielo(query, max_results=3):
    try:
        url = f"http://api.scielo.org/search/?q={urllib.parse.quote(query)}&lang=pt&limit={max_results}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            artigos = []
            for item in data.get("response", {}).get("docs", []):
                artigos.append({
                    "fonte": "SciELO",
                    "titulo": item.get("title", "Sem título"),
                    "resumo": item.get("abstract", "Resumo não disponível.")[:800],
                    "link": item.get("url", "")
                })
            return artigos
        return []
    except Exception as e:
        logger.error(f"Erro SciELO: {e}")
        return []

def buscar_lilacs(query, max_results=3):
    try:
        url = "https://pesquisa.bvsalud.org/portal/api/es/search"
        params = {
            "q": query,
            "lang": "pt",
            "count": max_results,
            "collection": "LILACS"
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            artigos = []
            for doc in data.get("documents", []):
                artigos.append({
                    "fonte": "LILACS",
                    "titulo": doc.get("title", "Sem título"),
                    "resumo": doc.get("abstract", "Resumo não disponível.")[:800],
                    "link": doc.get("url", "")
                })
            return artigos
        return []
    except Exception as e:
        logger.error(f"Erro LILACS: {e}")
        return []

def buscar_todas_fontes(query):
    pubmed_arts = buscar_pubmed(query, max_results=3)
    scielo_arts = buscar_scielo(query, max_results=3)
    lilacs_arts = buscar_lilacs(query, max_results=3)
    todos = pubmed_arts + scielo_arts + lilacs_arts
    vistos = set()
    unicos = []
    for art in todos:
        titulo = art["titulo"].lower()
        if titulo not in vistos:
            vistos.add(titulo)
            unicos.append(art)
    return unicos[:7]

def sintetizar_artigos_com_ia(query, artigos):
    if not artigos:
        return "Nenhum artigo encontrado."
    texto_artigos = "\n\n".join([f"Fonte: {a['fonte']}\nTítulo: {a['titulo']}\nResumo: {a['resumo']}" for a in artigos])
    prompt = f"""
Você é um especialista em síntese de evidências científicas. Com base nos artigos abaixo sobre "{query}", crie um resumo conciso destacando os principais achados, consensos e lacunas. Seja objetivo, em português.

Artigos:
{texto_artigos}

Síntese:
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        if response.status_code == 200:
            res_data = response.json()
            return res_data['candidates'][0]['content']['parts'][0]['text']
        else:
            return "Não foi possível gerar síntese (erro na IA)."
    except Exception as e:
        logger.error(f"Erro síntese IA: {e}")
        return "Erro ao gerar síntese."

# ================= SERVIDOR FLASK =================
app = Flask(__name__)
app.secret_key = SECRET_KEY if SECRET_KEY else secrets.token_hex(32)

def gerar_token_dashboard(user_id):
    """Gera token temporário de 1h para acesso ao dashboard sem expor user_id na URL."""
    token = secrets.token_urlsafe(32)
    expira = datetime.now() + timedelta(hours=1)
    tokens_coll.update_one(
        {"user_id": user_id},
        {"$set": {"token": token, "expira_em": expira}},
        upsert=True
    )
    return token

def validar_token_dashboard(token):
    """Retorna user_id se token válido, None se inválido/expirado."""
    if not token:
        return None
    doc = tokens_coll.find_one({"token": token})
    if not doc:
        return None
    if doc.get("expira_em", datetime.min) < datetime.now():
        tokens_coll.delete_one({"token": token})
        return None
    return doc["user_id"]

@app.route('/')
def home():
    return "MestreFisio V5.0 - Servidor Ativo 🧠"

@app.route('/admin')
def admin_dashboard():
    token = request.args.get('token')
    user_id = validar_token_dashboard(token)
    if not user_id or not is_admin(user_id):
        return "Acesso negado. Use o bot para gerar um link válido.", 403
    total_usuarios = uso_coll.count_documents({})
    total_pacientes = pacientes_coll.count_documents({})
    total_analises = logs_coll.count_documents({})
    ultimos_usuarios = list(uso_coll.find().sort("_id", -1).limit(10))
    return render_template_string(ADMIN_TEMPLATE,
                                  total_usuarios=total_usuarios,
                                  total_pacientes=total_pacientes,
                                  total_analises=total_analises,
                                  ultimos_usuarios=ultimos_usuarios)

@app.route('/profissional')
def profissional_dashboard():
    token = request.args.get('token')
    user_id = validar_token_dashboard(token)
    if not user_id:
        return "Link inválido ou expirado. Use o bot para gerar um novo link.", 401
    profissional = uso_coll.find_one({"user_id": user_id})
    if not profissional:
        return "Profissional não encontrado.", 404
    pacientes = list(pacientes_coll.find({"profissional_id": user_id}).sort("criado_em", -1))
    mensagem = request.args.get('msg', '')
    return render_template_string(PROFISSIONAL_TEMPLATE,
                                  profissional=profissional,
                                  pacientes=pacientes,
                                  admin_id=ADMIN_ID,
                                  token=token,
                                  mensagem=mensagem)

@app.route('/profissional/alterar-status', methods=['POST'])
def alterar_status_web():
    token = request.form.get('token')
    user_id = validar_token_dashboard(token)
    if not user_id:
        return "Link inválido ou expirado.", 401
    nome = request.form.get('nome', '').strip()
    novo_status = request.form.get('novo_status', '').strip()
    if not nome or novo_status not in ('ativo', 'alta'):
        return "Dados inválidos.", 400
    paciente = pacientes_coll.find_one({"profissional_id": user_id, "nome": nome})
    if not paciente:
        return "Paciente não encontrado.", 404
    pacientes_coll.update_one(
        {"profissional_id": user_id, "nome": nome},
        {"$set": {"status": novo_status,
                  "data_alta": datetime.now() if novo_status == "alta" else None}}
    )
    from flask import redirect
    return redirect(f"/profissional?token={token}&msg=Status+de+{nome}+alterado+para+{novo_status.upper()}")

_CSS_BASE = """
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#f0f4f8;color:#333;padding:20px}
  .card{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
  h1{color:#1a73e8;margin-bottom:4px;font-size:1.6rem}
  h2{color:#333;margin:16px 0 8px;font-size:1.1rem}
  .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.8rem;font-weight:600}
  .badge-gratuito{background:#e8f0fe;color:#1a73e8}
  .badge-prata{background:#f3e8ff;color:#7b2ff7}
  .badge-ouro{background:#fff8e1;color:#f9a825}
  .badge-diamante{background:#e8f5e9;color:#2e7d32}
  .badge-admin{background:#fce8e6;color:#c62828}
  .stat{text-align:center;padding:16px}
  .stat-num{font-size:2.2rem;font-weight:700;color:#1a73e8}
  .stat-label{font-size:.85rem;color:#666;margin-top:4px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
  table{width:100%;border-collapse:collapse}
  th{background:#f8f9fa;padding:10px 12px;text-align:left;font-size:.85rem;color:#555;border-bottom:2px solid #e0e0e0}
  td{padding:10px 12px;border-bottom:1px solid #f0f0f0;font-size:.9rem;vertical-align:middle}
  tr:hover td{background:#f8f9fe}
  .status-ativo{color:#2e7d32;font-weight:600}
  .status-alta{color:#b71c1c;font-weight:600}
  .btn{display:inline-block;padding:4px 12px;border-radius:6px;border:none;cursor:pointer;font-size:.8rem;font-weight:600;transition:opacity .15s}
  .btn:hover{opacity:.8}
  .btn-alta{background:#fce8e6;color:#c62828}
  .btn-ativo{background:#e8f5e9;color:#2e7d32}
  .alert{padding:12px 16px;border-radius:8px;background:#e8f5e9;color:#2e7d32;font-weight:600;margin-bottom:16px}
  .footer{text-align:center;color:#aaa;font-size:.8rem;margin-top:24px}
  @media(max-width:600px){table,thead,tbody,th,td,tr{display:block}
    th{display:none}td{padding:6px 0;border:none}td:before{font-weight:600;margin-right:6px}}
</style>
"""

ADMIN_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>Admin – MestreFisio</title>""" + _CSS_BASE + """</head>
<body>
<div class="card">
  <h1>🛡️ Painel Administrativo</h1>
  <p style="color:#888;font-size:.85rem">MestreFisio PhD – visão geral da plataforma</p>
</div>
<div class="card">
  <div class="grid">
    <div class="stat"><div class="stat-num">{{ total_usuarios }}</div><div class="stat-label">Usuários cadastrados</div></div>
    <div class="stat"><div class="stat-num">{{ total_pacientes }}</div><div class="stat-label">Pacientes no sistema</div></div>
    <div class="stat"><div class="stat-num">{{ total_analises }}</div><div class="stat-label">Análises realizadas</div></div>
  </div>
</div>
<div class="card">
  <h2>Últimos 10 usuários cadastrados</h2>
  <table>
    <tr><th>ID Telegram</th><th>Nome</th><th>Plano</th><th>PRO</th><th>Cadastro</th></tr>
    {% for u in ultimos_usuarios %}
    <tr>
      <td style="font-family:monospace;color:#555">{{ u.user_id }}</td>
      <td>{{ u.nome_profissional or '—' }}</td>
      <td>
        {% if u.plano == 'prata' %}<span class="badge badge-prata">⭐ Prata</span>
        {% elif u.plano == 'ouro' %}<span class="badge badge-ouro">🌟 Ouro</span>
        {% elif u.plano == 'diamante' %}<span class="badge badge-diamante">💎 Diamante</span>
        {% else %}<span class="badge badge-gratuito">Gratuito</span>{% endif %}
      </td>
      <td>{{ '✅' if u.pro else '—' }}</td>
      <td style="color:#888;font-size:.82rem">{{ u.criado_em or '—' }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
<p class="footer">MestreFisio PhD · Link válido por 1h · Gerado pelo bot</p>
</body></html>
"""

PROFISSIONAL_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>Painel – MestreFisio</title>""" + _CSS_BASE + """</head>
<body>
<div class="card">
  <h1>👋 Olá, {{ profissional.nome_profissional or 'Profissional' }}</h1>
  <p style="color:#888;font-size:.9rem">{{ profissional.registro_profissional or 'Registro não informado' }}</p>
  <div style="margin-top:12px">
    {% if profissional.user_id == admin_id %}
      <span class="badge badge-admin">👑 Administrador</span>
    {% elif profissional.plano == 'prata' %}
      <span class="badge badge-prata">⭐ Plano Prata</span>
    {% elif profissional.plano == 'ouro' %}
      <span class="badge badge-ouro">🌟 Plano Ouro</span>
    {% elif profissional.plano == 'diamante' %}
      <span class="badge badge-diamante">💎 Plano Diamante</span>
    {% else %}
      <span class="badge badge-gratuito">🚀 Plano Gratuito</span>
    {% endif %}
  </div>
</div>
{% if mensagem %}
<div class="alert">✅ {{ mensagem }}</div>
{% endif %}
<div class="card">
  <h2>👥 Pacientes ({{ pacientes|length }})</h2>
  {% if pacientes %}
  <table>
    <tr><th>Nome</th><th>Status</th><th>Última análise</th><th>Cadastro</th><th>Ação</th></tr>
    {% for p in pacientes %}
    <tr>
      <td><strong>{{ p.nome }}</strong></td>
      <td>
        {% if p.status == 'alta' %}<span class="status-alta">🔴 Alta</span>
        {% else %}<span class="status-ativo">🟢 Ativo</span>{% endif %}
      </td>
      <td style="color:#888;font-size:.85rem">{{ p.data or '—' }}</td>
      <td style="color:#aaa;font-size:.82rem">{{ p.criado_em.strftime('%d/%m/%Y') if p.criado_em and p.criado_em.__class__.__name__ == 'datetime' else (p.criado_em or '—') }}</td>
      <td>
        {% if p.status == 'alta' %}
        <form method="POST" action="/profissional/alterar-status" style="display:inline">
          <input type="hidden" name="token" value="{{ token }}">
          <input type="hidden" name="nome" value="{{ p.nome }}">
          <input type="hidden" name="novo_status" value="ativo">
          <button type="submit" class="btn btn-ativo">→ Ativo</button>
        </form>
        {% else %}
        <form method="POST" action="/profissional/alterar-status" style="display:inline">
          <input type="hidden" name="token" value="{{ token }}">
          <input type="hidden" name="nome" value="{{ p.nome }}">
          <input type="hidden" name="novo_status" value="alta">
          <button type="submit" class="btn btn-alta">→ Alta</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p style="color:#aaa;text-align:center;padding:24px">Nenhum paciente cadastrado ainda.</p>
  {% endif %}
</div>
<p class="footer">MestreFisio PhD · Link válido por 1h · Gerado pelo bot</p>
</body></html>
"""

def run_flask():
    app.run(host='0.0.0.0', port=10000)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# =================================================================
# BLOCO 2 - BOT, PROMPTS, MENU PRINCIPAL, HANDLERS E COMANDOS
# =================================================================

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
user_state = {}
_state_lock = threading.Lock()

# ================= PROMPTS =================
PROMPT_SISTEMA_COMPLETO = """
Atue como um Fisioterapeuta PhD especialista em ortopedia, biomecânica, medicina esportiva, reabilitação funcional e raciocínio clínico avançado, com domínio de literatura científica e prática clínica baseada em evidências. Sua função é realizar análise clínica profunda, estruturada e aplicada, simulando o raciocínio de um especialista experiente.

OBJETIVO:
Fornecer respostas com raciocínio clínico estruturado, profundidade técnica avançada, aplicabilidade prática, integração entre anatomia, biomecânica e fisiopatologia, e abordagem funcional baseada em evidência.

ESTRUTURA OBRIGATÓRIA (SEMPRE USAR E NUNCA OMITIR ETAPAS):

1. Definição clínica
2. Anatomia e biomecânica envolvida
3. Etiologia / causas
4. Sinais e sintomas
5. Raciocínio clínico
6. Avaliação clínica
7. Testes clínicos
8. Diagnósticos diferenciais
9. Exames complementares
10. Classificação da lesão
11. Conduta fisioterapêutica
12. Protocolo em atletas
13. Algoritmo clínico
14. Red flags
15. Evidência científica

REGRAS:
- Não fornecer respostas superficiais
- Priorizar clareza e profundidade
- Pensar como clínico experiente
"""

PROMPT_DUVIDA_TECNICA = """
Atue como um Fisioterapeuta PhD. O profissional tem uma dúvida sobre uma condição específica. Forneça uma resposta direta e resumida, com foco em:
1. Sugestão de anamnese direcionada
2. Principais testes clínicos para diagnóstico
3. Primeiras condutas seguras e baseadas em evidência
4. Educação em Dor (explicações para o paciente)

Seja objetivo, prático e evite aprofundamento excessivo.
"""

PROMPTS_LAUDO = {
    "clinico": "Gere um laudo clínico conciso e objetivo (máximo 1 página). Inclua: 1) Resumo do caso, 2) Diagnóstico principal, 3) Conduta terapêutica, 4) Prognóstico. Seja direto e evite repetições.",
    "exercicios": "Gere um programa de exercícios terapêuticos individualizado para este paciente (máximo 1 página). Use exercícios baseados em evidências: Ponte Glútea, Bird Dog, Dead Bug, Prancha, Calf Raise Excêntrico, Nordic Hamstring, Hip Thrust, Clamshell, Chin Tuck, Rotação com Elástico, Step Up, entre outros adequados ao caso. Inclua: 1) Fase do tratamento (aguda/subaguda/crônica), 2) Objetivos terapêuticos, 3) Lista de exercícios com nome, execução detalhada, séries, repetições e progressão, 4) Frequência semanal e precauções. Adapte ao diagnóstico e limitações do paciente.",
    "evolucao": "Gere um relato de evolução clínica objetiva (máximo 1 página). Inclua: 1) Resumo da evolução, 2) Comparação com avaliação anterior, 3) Ajustes na conduta, 4) Metas.",
    "atestado": "Gere um atestado médico profissional (máximo 1 página). Inclua: 1) Identificação do paciente, 2) Período de afastamento (se aplicável), 3) CID e justificativa, 4) Recomendações. Formato oficial.",
    "tratamento": "Gere um plano de tratamento estruturado (máximo 1 página). Inclua: 1) Objetivos de curto/médio/longo prazo, 2) Modalidades terapêuticas, 3) Cronograma, 4) Critérios de alta.",
    "convenio": "Gere um relatório para convênio (máximo 1 página). Inclua: 1) Diagnóstico, 2) Evolução, 3) Sessões realizadas, 4) Resultados alcançados, 5) Necessidade de continuidade.",
    "biomecanica": "Gere uma análise biomecânica funcional (máximo 1 página). Inclua: 1) Análise de cadeia cinética, 2) Compensações observadas, 3) Estratégias de correção, 4) Exercícios específicos."
}

# =================================================================
# BANCO DE EXERCÍCIOS TERAPÊUTICOS
# =================================================================
BANCO_EXERCICIOS = {
    "🔙 Coluna Cervical": [
        {"nome": "Flexão Cervical Ativa", "exec": "Sentado, queixo em direção ao peito lentamente", "sr": "3×10", "nivel": "🟢 Iniciante", "obj": "Mobilidade flexora"},
        {"nome": "Extensão Cervical Ativa", "exec": "Sentado, cabeça para trás com controle", "sr": "3×10", "nivel": "🟢 Iniciante", "obj": "Mobilidade extensora"},
        {"nome": "Inclinação Lateral Cervical", "exec": "Orelha em direção ao ombro ipsilateral, sem elevar o ombro", "sr": "3×10 cada lado", "nivel": "🟢 Iniciante", "obj": "Mobilidade lateral e alongamento"},
        {"nome": "Retração Cervical (Chin Tuck)", "exec": "Empurrar queixo para trás horizontalmente, 'duplo queixo'", "sr": "3×15 (5s)", "nivel": "🟢 Iniciante", "obj": "Estabilização profunda e postura"},
        {"nome": "Isometria Cervical Frontal", "exec": "Mão na testa, resistir à flexão sem mover a cabeça", "sr": "3×10 (6s)", "nivel": "🟡 Intermediário", "obj": "Fortalecimento flexores profundos"},
        {"nome": "Isometria Cervical Lateral", "exec": "Mão na têmpora, resistir à inclinação lateral", "sr": "3×10 (6s) cada lado", "nivel": "🟡 Intermediário", "obj": "Fortalecimento estabilizadores laterais"},
        {"nome": "Estabilização Cervical 4 Apoios", "exec": "Em quatro apoios, manter coluna neutra movendo membro contralateral", "sr": "3×10 cada lado", "nivel": "🔴 Avançado", "obj": "Controle motor cervical e dissociação"},
    ],
    "🔴 Coluna Lombar": [
        {"nome": "Ponte Glútea", "exec": "Decúbito dorsal, joelhos fletidos, elevar quadril contraindo glúteos", "sr": "3×15", "nivel": "🟢 Iniciante", "obj": "Glúteo máximo e estabilização lombar"},
        {"nome": "Báscula Pélvica", "exec": "Deitado, imprimir e reverter a lordose lombar no chão", "sr": "3×20", "nivel": "🟢 Iniciante", "obj": "Consciência pélvica e mobilidade"},
        {"nome": "Enrolamento Abdominal (Crunch)", "exec": "Decúbito dorsal, elevar escápulas sem tracionar o pescoço", "sr": "3×20", "nivel": "🟡 Intermediário", "obj": "Reto abdominal"},
        {"nome": "Prancha Frontal", "exec": "Apoio em antebraços e pontas dos pés, corpo alinhado", "sr": "3×30–60s", "nivel": "🟡 Intermediário", "obj": "Core global e estabilização"},
        {"nome": "Bird Dog", "exec": "Quatro apoios, estender braço e perna opostos simultaneamente", "sr": "3×12 cada lado", "nivel": "🟡 Intermediário", "obj": "Estabilização lombopélvica e controle motor"},
        {"nome": "Dead Bug", "exec": "Decúbito dorsal, braços e pernas no ar, abaixar membro oposto mantendo lombar neutra", "sr": "3×10 cada lado", "nivel": "🔴 Avançado", "obj": "Controle motor profundo e anti-extensão"},
        {"nome": "Extensão Lombar no Banco", "exec": "Decúbito ventral com quadril no banco, elevar tronco até neutro", "sr": "3×15", "nivel": "🔴 Avançado", "obj": "Extensores lombares e glúteos"},
        {"nome": "Mcgill Big Three – Curl Up", "exec": "Decúbito dorsal, uma perna fletida, elevar ligeiramente a cabeça e ombros", "sr": "5-3-1 (pirâmide)", "nivel": "🟡 Intermediário", "obj": "Resistência do core – protocolo McGill"},
    ],
    "🟡 Ombro": [
        {"nome": "Pêndulo de Codman", "exec": "Inclinado, braço solto pendendo, movimentos circulares passivos", "sr": "2×60s", "nivel": "🟢 Iniciante", "obj": "Mobilização passiva e analgesia"},
        {"nome": "Flexão Glenoumeral com Bastão", "exec": "Deitado, usar bastão para elevar o braço acometido com o saudável", "sr": "3×15", "nivel": "🟢 Iniciante", "obj": "Ganho de ADM em flexão"},
        {"nome": "Rotação Externa com Elástico", "exec": "Cotovelo a 90°, girar antebraço para fora com resistência elástica", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Manguito rotador – infraespinhoso e redondo menor"},
        {"nome": "Rotação Interna com Elástico", "exec": "Cotovelo a 90°, girar antebraço para dentro com resistência elástica", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Manguito rotador – subescapular"},
        {"nome": "Abdução Glenoumeral no Plano da Escápula", "exec": "Elevação do braço a 30° da frontal, polegar para cima", "sr": "3×12", "nivel": "🟡 Intermediário", "obj": "Supraespinhoso e deltóide médio"},
        {"nome": "Remada Baixa com Elástico", "exec": "Puxar elástico para o abdômen, cotovelos próximos ao corpo", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Romboides, trapézio médio e reto do ombro"},
        {"nome": "Press Overhead com Halteres", "exec": "Sentado, empurrar halteres acima da cabeça com controle", "sr": "3×12", "nivel": "🔴 Avançado", "obj": "Deltóide, trapézio superior e estabilização"},
        {"nome": "Exercício Y-T-W em Inclinado", "exec": "Deitado em prancha inclinada, executar os padrões Y, T e W com os braços", "sr": "3×10 cada padrão", "nivel": "🔴 Avançado", "obj": "Escapulotorácico e manguito rotador"},
    ],
    "🟠 Joelho": [
        {"nome": "Agachamento Cadeia Cinética Fechada", "exec": "Pés paralelos, descer até 60° de flexão com joelhos alinhados aos pés", "sr": "3×15", "nivel": "🟢 Iniciante", "obj": "Quadríceps, glúteo e co-contração"},
        {"nome": "Extensão de Joelho Isométrica", "exec": "Sentado, contrair quadríceps pressionando joelho no colchão", "sr": "3×15 (6s)", "nivel": "🟢 Iniciante", "obj": "Quadríceps – fase aguda pós-lesão"},
        {"nome": "SLR – Elevação do Membro Inferior Estendido", "exec": "Decúbito dorsal, elevar o membro estendido a 45° contraindo o quadríceps", "sr": "3×20", "nivel": "🟢 Iniciante", "obj": "Quadríceps – fase precoce"},
        {"nome": "Step Up Frontal", "exec": "Subir e descer degrau controlando a flexão do joelho, sem valgo", "sr": "3×12 cada perna", "nivel": "🟡 Intermediário", "obj": "Quadríceps, glúteo e estabilidade funcional"},
        {"nome": "Leg Press Unilateral", "exec": "Em leg press, trabalhar uma perna por vez, amplitude de 0-90°", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Quadríceps e glúteo com carga controlada"},
        {"nome": "Agachamento Búlgaro", "exec": "Pé traseiro elevado, descer com o joelho dianteiro alinhado", "sr": "3×10 cada perna", "nivel": "🔴 Avançado", "obj": "Quadríceps, glúteo e estabilidade unilateral"},
        {"nome": "Nórdico (Nordic Hamstring)", "exec": "Ajoelhado com pés fixos, cair à frente controlando a excentrica", "sr": "3×6–8", "nivel": "🔴 Avançado", "obj": "Isquiotibiais – prevenção e reabilitação de lesão"},
        {"nome": "Ponte Single Leg com Joelho Fletido", "exec": "Ponte glútea em apoio unilateral, joelho contralateral a 90°", "sr": "3×12 cada perna", "nivel": "🟡 Intermediário", "obj": "Glúteo máximo e estabilização do joelho"},
    ],
    "🟤 Quadril": [
        {"nome": "Abdução de Quadril em Decúbito Lateral", "exec": "Deitado de lado, elevar membro superior estendido a 40°", "sr": "3×20", "nivel": "🟢 Iniciante", "obj": "Glúteo médio"},
        {"nome": "Clamshell (Mexilhão)", "exec": "Decúbito lateral com quadris e joelhos fletidos, abrir e fechar como mexilhão", "sr": "3×20", "nivel": "🟢 Iniciante", "obj": "Glúteo médio e rotadores externos"},
        {"nome": "Extensão de Quadril em 4 Apoios", "exec": "Em quatro apoios, estender um membro inferior mantendo coluna neutra", "sr": "3×15 cada lado", "nivel": "🟡 Intermediário", "obj": "Glúteo máximo e estabilização lombar"},
        {"nome": "Monster Walk com Elástico", "exec": "Elástico nos tornozelos, passos laterais mantendo semi-agachamento", "sr": "3×10m cada lado", "nivel": "🟡 Intermediário", "obj": "Glúteo médio e coordenação"},
        {"nome": "Hip Thrust com Barra", "exec": "Ombros no banco, barra sobre quadril, elevar o quadril com contração glútea", "sr": "3×12", "nivel": "🔴 Avançado", "obj": "Glúteo máximo – máxima ativação"},
        {"nome": "Rotação Interna/Externa de Quadril Sentado", "exec": "Sentado, girar a perna medial e lateralmente com amplitude máxima", "sr": "3×15 cada rotação", "nivel": "🟢 Iniciante", "obj": "Mobilidade rotatória do quadril"},
    ],
    "🔵 Tornozelo e Pé": [
        {"nome": "Exercício Alfabeto com o Tornozelo", "exec": "Escrever as letras do alfabeto com o hálux, tornozelo livre", "sr": "2 séries", "nivel": "🟢 Iniciante", "obj": "Mobilidade global do tornozelo – fase aguda"},
        {"nome": "Elevação de Calcanhares (Calf Raise)", "exec": "Em pé, elevar os calcanhares contraindo o tríceps sural", "sr": "3×20", "nivel": "🟢 Iniciante", "obj": "Gastrocnêmio e sóleo"},
        {"nome": "Calf Raise Excêntrico em Degrau", "exec": "Subir com os dois pés, descer lentamente em 6s em apoio unilateral", "sr": "3×15 cada perna", "nivel": "🟡 Intermediário", "obj": "Reabilitação de tendão calcâneo – protocolo Alfredson"},
        {"nome": "Equilíbrio Unipodal Olhos Fechados", "exec": "Apoio em um pé, olhos fechados, manter equilíbrio por 30s", "sr": "3×30s cada perna", "nivel": "🟡 Intermediário", "obj": "Propriocepção e controle neuromuscular"},
        {"nome": "Mini Agachamento em Prancha de Equilíbrio", "exec": "Sobre prancha instável, realizar mini-agachamento em apoio unilateral", "sr": "3×12 cada perna", "nivel": "🔴 Avançado", "obj": "Propriocepção avançada e força funcional"},
        {"nome": "Hop Test Progressivo", "exec": "Saltos unilaterais para frente, lateral e em cruz com aterrissagem controlada", "sr": "3×5 cada direção", "nivel": "🔴 Avançado", "obj": "Retorno ao esporte – potência e controle"},
    ],
    "⚪ Cotovelo e Punho": [
        {"nome": "Flexão/Extensão de Punho com Haltere", "exec": "Antebraço apoiado, realizar flexão e extensão de punho com carga leve", "sr": "3×20 cada movimento", "nivel": "🟢 Iniciante", "obj": "Flexores e extensores do punho"},
        {"nome": "Pronação e Supinação com Martelo", "exec": "Cotovelo a 90°, girar o martelo de forma controlada", "sr": "3×20 cada lado", "nivel": "🟢 Iniciante", "obj": "Pronadores e supinadores – epicondilalgia"},
        {"nome": "Extensão de Punho Excêntrica (Tyler Twist)", "exec": "Usando barra flexível ou theraband: extensão excêntrica de punho em pronação", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Epicondilite lateral – protocolo Tyler"},
        {"nome": "Flexão de Cotovelo com Elástico", "exec": "Em pé, cotovelo fixo ao tronco, flexionar contra resistência do elástico", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Bíceps braquial e supinadores"},
        {"nome": "Squeeze de Bola Antistress", "exec": "Apertar bola maleável repetidamente, variando a pressão", "sr": "3×30", "nivel": "🟢 Iniciante", "obj": "Preensão palmar e musculatura intrínseca"},
        {"nome": "Extensão de Cotovelo com Elástico (Tríceps)", "exec": "Elástico fixo acima, estender o cotovelo completamente", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Tríceps braquial"},
    ],
    "🟣 Core e Postura Global": [
        {"nome": "Prancha Lateral", "exec": "Apoio em antebraço e borda lateral do pé, corpo alinhado", "sr": "3×30s cada lado", "nivel": "🟡 Intermediário", "obj": "Oblíquos, quadrado lombar e estabilidade lateral"},
        {"nome": "Prancha com Toque Alternado de Ombro", "exec": "Em posição de flexão, tocar o ombro oposto alternadamente sem rotação de tronco", "sr": "3×20", "nivel": "🔴 Avançado", "obj": "Anti-rotação e estabilidade de core"},
        {"nome": "Rollout com Roda Abdominal", "exec": "Ajoelhado, rolar a roda à frente mantendo abdômen contraído, voltar lentamente", "sr": "3×10", "nivel": "🔴 Avançado", "obj": "Core anti-extensão – ativação intensa"},
        {"nome": "Paloff Press com Elástico", "exec": "De pé perpendicular ao elástico, pressionar à frente e retornar sem rotação", "sr": "3×12 cada lado", "nivel": "🟡 Intermediário", "obj": "Anti-rotação e controle de tronco"},
        {"nome": "Exercício de Dissociação Escapular", "exec": "Em pé com elástico, protrair e retrair as escápulas com controle", "sr": "3×15", "nivel": "🟢 Iniciante", "obj": "Ritmidade escapuloumeral e postura"},
        {"nome": "Respiração Diafragmática com Feedback", "exec": "Deitado, mão no abdômen, inspirar expandindo o abdômen, expirar lentamente", "sr": "3×10 respirações", "nivel": "🟢 Iniciante", "obj": "Diafragma, PIA e estabilização profunda"},
        {"nome": "Agachamento Goblet", "exec": "Segurar kettlebell/haltere no peito, agachar com tronco ereto", "sr": "3×15", "nivel": "🟡 Intermediário", "obj": "Quadríceps, glúteo, core e postura global"},
    ],
    "🏃 Retorno ao Esporte": [
        {"nome": "Corrida em Linha Reta Progressiva", "exec": "Iniciar a 50% da velocidade, progredir 10% a cada sessão sem dor", "sr": "10–20 min", "nivel": "🟡 Intermediário", "obj": "Recondicionamento cardiovascular e confiança"},
        {"nome": "Skipping e Corrida Lateral", "exec": "Exercícios de agilidade em escada de agilidade: skipping, passadas laterais", "sr": "3×10m cada", "nivel": "🔴 Avançado", "obj": "Agilidade, coordenação e velocidade de reação"},
        {"nome": "Salto Vertical com Aterrissagem (Drop Jump)", "exec": "Cair de uma caixa baixa e imediatamente saltar, aterrissar com joelhos alinhados", "sr": "3×8", "nivel": "🔴 Avançado", "obj": "Pliometria e mecanismo de lesão reverso (ACL)"},
        {"nome": "Change of Direction 5-10-5", "exec": "Correr 5 metros, tocar o cone, 10 metros para o outro lado, retornar 5 metros", "sr": "5×", "nivel": "🔴 Avançado", "obj": "Mudança de direção e agilidade específica"},
        {"nome": "Trabalho com Bola Específico do Esporte", "exec": "Passes, recepções e dribles em intensidade crescente", "sr": "15–30 min", "nivel": "🔴 Avançado", "obj": "Habilidade técnica e confiança psicológica"},
    ],
}

REGIOES_BANCO = list(BANCO_EXERCICIOS.keys())

def formatar_exercicio(ex):
    return (
        f"🏋️ *{ex['nome']}*\n"
        f"▶️ *Execução:* {ex['exec']}\n"
        f"🔢 *Séries/Reps:* {ex['sr']}\n"
        f"📶 *Nível:* {ex['nivel']}\n"
        f"🎯 *Objetivo:* {ex['obj']}"
    )

# ================= FUNÇÃO DE CHAMADA À IA =================
def chamar_gemini(message, prompt, nome_paciente=None, tipo="analise"):
    if not is_admin(message.from_user.id):
        registrar_usuario_se_novo(message.from_user.id)
        if not pode_usar_recurso(message.from_user.id, tipo):
            bot.send_message(message.chat.id, "🚫 Limite de análises gratuitas atingido. Considere um dos planos pagos.")
            return None

    aguarde = bot.send_message(message.chat.id, "🧠 Processando...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        if response.status_code != 200:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "❌ Erro na API da IA.")
            logger.error(f"Gemini API error {response.status_code}: {response.text[:500]}")
            return None
        res_data = response.json()
        try:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError) as e:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "⚠️ Erro ao interpretar resposta da IA.")
            logger.error(f"Erro parsing resposta Gemini: {e} | Resposta: {str(res_data)[:300]}")
            return None

        if nome_paciente and tipo == "analise":
            pacientes_coll.update_one(
                {"profissional_id": message.from_user.id, "nome": nome_paciente},
                {"$set": {"ultima_analise": analise, "data": datetime.now().strftime("%d/%m/%Y")}},
                upsert=True
            )
            logs_coll.insert_one({
                "user_id": message.from_user.id,
                "paciente": nome_paciente,
                "data": datetime.now(),
                "tipo": "analise"
            })

        bot.delete_message(message.chat.id, aguarde.message_id)
        for p in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
            bot.send_message(message.chat.id, p)
            time.sleep(1)
        bot.send_message(message.chat.id, "✅ Finalizado.", reply_markup=menu_principal())
        return analise
    except Exception as e:
        logger.error(f"Erro inesperado chamar_gemini: {e}")
        bot.send_message(message.chat.id, "❌ Erro na IA. Tente novamente.")
        return None

# ================= MENU PRINCIPAL =================
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("👥 Pacientes", callback_data="pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("📷 Analisar Laudo", callback_data="analisar_laudo"),
        types.InlineKeyboardButton("🔍 Buscar Artigos", callback_data="buscar_artigos"),
        types.InlineKeyboardButton("🏋️ Banco de Exercícios", callback_data="banco_exercicios"),
        types.InlineKeyboardButton("💰 Planos Pagos", callback_data="planos"),
        types.InlineKeyboardButton("🌐 Dashboard", callback_data="dashboard"),
        types.InlineKeyboardButton("🎁 Indique um colega", callback_data="indicar")
    )
    if ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Métricas (Admin)", callback_data="metricas_admin"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    args = message.text.split()
    codigo = args[1] if len(args) > 1 else None
    registrar_usuario_se_novo(message.from_user.id, codigo)
    if not verificar_dados_profissional(message):
        return
    bot.send_message(message.chat.id, "🚀 *MestreFisio V5.0 Especialista*\nAgora com memória clínica inteligente.\n\nUse /status para ver seu plano e uso mensal.", parse_mode='Markdown', reply_markup=menu_principal())

# ================= CAPTURA DE DADOS DO PROFISSIONAL =================
def verificar_dados_profissional(message):
    user = uso_coll.find_one({"user_id": message.from_user.id})
    if not user or not user.get("nome_profissional") or not user.get("registro_profissional"):
        msg = bot.send_message(message.chat.id, "📝 Antes de continuar, preciso do seu nome completo e número de registro profissional (Crefito).\n\nEnvie no formato:\n`Nome Completo | Crefito 123456`", parse_mode='Markdown')
        bot.register_next_step_handler(msg, salvar_dados_profissional)
        return False
    return True

def salvar_dados_profissional(message):
    try:
        texto = (message.text or "").strip()
        partes = texto.split('|')
        if len(partes) < 2:
            raise ValueError("Separador | não encontrado")
        nome = partes[0].strip()[:120]
        registro = partes[1].strip()[:60]
        if not nome or not registro:
            raise ValueError("Nome ou registro vazio")
        uso_coll.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"nome_profissional": nome, "registro_profissional": registro}}
        )
        bot.send_message(message.chat.id, f"✅ Dados salvos:\n👤 {nome}\n🆔 {registro}\n\nAgora você pode usar todas as funcionalidades!", reply_markup=menu_principal())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Formato inválido. Use exatamente:\n`Nome Completo | Crefito 123456`\nTente novamente.", parse_mode='Markdown')
        verificar_dados_profissional(message)
    except Exception as e:
        logger.error(f"Erro ao salvar dados profissional: {e}")
        bot.send_message(message.chat.id, "❌ Erro interno. Tente novamente mais tarde.")

# ================= HANDLERS DOS COMANDOS =================
@bot.message_handler(commands=['historico'])
def cmd_historico(message):
    pacientes = list(pacientes_coll.find({"profissional_id": message.from_user.id}))
    if not pacientes:
        bot.send_message(message.chat.id, "📭 Nenhum paciente cadastrado.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in pacientes:
        markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"paciente_{p['nome']}"))
    bot.send_message(message.chat.id, "👥 Selecione o paciente para ver histórico:", reply_markup=markup)

@bot.message_handler(commands=['planos'])
def cmd_planos(message):
    texto = """
💎 **Planos MestreFisio PhD**

🚀 **Gratuito** – 5 análises/mês | 5 buscas científicas/mês
⭐ **Prata** – 30 análises/mês | 30 buscas – R$ 49,90/mês
🌟 **Ouro** – 60 análises/mês | 60 buscas – R$ 69,90/mês
💎 **Diamante** – 300 análises/mês | 300 buscas – R$ 99,90/mês

✅ Todos os planos incluem:
• Laudos e atestados personalizados
• Memória clínica inteligente
• Busca em PubMed, SciELO e LILACS
• Suporte prioritário

🎁 **Indicação premiada**: Indique um colega e ganhe 25% de desconto na próxima mensalidade (acumulável até 50%). O colega indicado também ganha 25% de desconto no primeiro mês!
"""
    bot.send_message(message.chat.id, texto, parse_mode='Markdown', reply_markup=menu_principal())

@bot.message_handler(commands=['ajuda'])
def cmd_ajuda(message):
    ajuda_texto = """
📘 **Ajuda – MestreFisio V5.0**

🔹 *Novo Paciente* – Cadastre um paciente e faça a primeira análise (resumo, prognóstico, condutas).
🔹 *Pacientes* – Veja lista, histórico, evolua ou gere laudos.
🔹 *Dúvida Técnica* – Tire dúvidas clínicas rapidamente (anamnese, testes, condutas seguras e educação em dor).
🔹 *Analisar Laudo* – Envie imagem/PDF de laudos médicos para interpretação.
🔹 *Buscar Artigos* – Pesquise evidências em PubMed, SciELO e LILACS e receba uma síntese.
🔹 *Planos Pagos* – Assine um dos planos (Prata, Ouro, Diamante) com acesso ampliado.
🔹 *Dashboard* – Acesse seu painel profissional online.
🔹 *Indique um colega* – Ganhe descontos ao indicar outros profissionais.

Comandos rápidos:
/historico – Lista pacientes
/planos – Detalhes dos planos
/status – Ver uso do mês e plano atual
/ajuda – Este texto
/dashboard – Link para painel (válido 1h)
/indicar – Gerar link de indicação
"""
    bot.send_message(message.chat.id, ajuda_texto, parse_mode='Markdown', reply_markup=menu_principal())

@bot.message_handler(commands=['consulta'])
def cmd_consulta(message):
    msg = bot.send_message(message.chat.id, "💡 Qual condição deseja analisar hoje?")
    bot.register_next_step_handler(msg, processar_ia_direta)

@bot.message_handler(commands=['dashboard'])
def cmd_dashboard(message):
    user_id = message.from_user.id
    token = gerar_token_dashboard(user_id)
    link_prof = f"{DOMAIN}/profissional?token={token}"
    bot.send_message(message.chat.id, f"🌐 Acesse seu painel profissional (válido por 1h):\n{link_prof}")
    if is_admin(user_id):
        link_admin = f"{DOMAIN}/admin?token={token}"
        bot.send_message(message.chat.id, f"👑 Link admin (válido por 1h):\n{link_admin}")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    user_id = message.from_user.id
    if is_admin(user_id):
        bot.send_message(message.chat.id, "👑 Você é administrador – sem limites de uso.", reply_markup=menu_principal())
        return
    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        bot.send_message(message.chat.id, "❌ Conta não encontrada. Use /start para começar.", reply_markup=menu_principal())
        return
    verificar_assinatura(user)
    user = uso_coll.find_one({"user_id": user_id})
    plano = user.get("plano", "gratuito") if user.get("pro") else "gratuito"
    limites = obter_limites_plano(plano)
    uso_mes = user.get("uso_mes", 0)
    laudos_mes = user.get("laudos_mes", 0)
    uso_buscas = user.get("uso_buscas", 0)
    total_pac = pacientes_coll.count_documents({"profissional_id": user_id})
    emojis = {"gratuito": "🚀", "prata": "⭐", "ouro": "🌟", "diamante": "💎"}
    emoji = emojis.get(plano, "🚀")
    expira_txt = ""
    if user.get("pro") and user.get("pro_expira_em"):
        dias_restantes = int((user["pro_expira_em"] - time.time()) / 86400)
        expira_txt = f"\n⏳ Plano expira em: {max(0, dias_restantes)} dias"
    texto = (
        f"{emoji} *Plano atual: {plano.capitalize()}*{expira_txt}\n\n"
        f"📊 *Uso do mês:*\n"
        f"• Análises: {uso_mes}/{limites['analises']}\n"
        f"• Laudos: {laudos_mes}/{limites['laudos']}\n"
        f"• Buscas científicas: {uso_buscas}/{limites['buscas']}\n"
        f"• Pacientes: {total_pac}/{limites['pacientes']}\n\n"
        f"🎁 Descontos acumulados: {user.get('creditos_desconto', 0)}%"
    )
    bot.send_message(message.chat.id, texto, parse_mode='Markdown', reply_markup=menu_principal())

@bot.message_handler(commands=['indicar'])
def cmd_indicar(message):
    user = uso_coll.find_one({"user_id": message.from_user.id})
    if not user:
        registrar_usuario_se_novo(message.from_user.id)
        user = uso_coll.find_one({"user_id": message.from_user.id})
    codigo = user.get("codigo_indicacao")
    link = f"https://t.me/{bot.get_me().username}?start={codigo}"

    explicacao = (
        f"🎁 *Sistema de Indicação Premiada*\n\n"
        f"Você recebe um código exclusivo: `{codigo}`\n\n"
        f"*Como funciona:*\n"
        f"• Compartilhe seu código com colegas fisioterapeutas.\n"
        f"• Cada novo cadastro usando seu código lhe dá **25% de desconto** na próxima mensalidade.\n"
        f"• O desconto pode acumular até **50%** por mês; o saldo não utilizado fica para meses futuros.\n"
        f"• O colega indicado também ganha **25% de desconto** no primeiro mês!\n\n"
        f"Quanto mais indicar, mais desconto! 🚀"
    )
    bot.send_message(message.chat.id, explicacao, parse_mode='Markdown')

    convite = (
        f"🌟 *MestreFisio – Seu assistente de IA para fisioterapia!*\n\n"
        f"Olá! Estou usando o MestreFisio e recomendo. É uma plataforma completa com:\n"
        f"✅ Análises clínicas profundas\n"
        f"✅ Laudos e atestados personalizados\n"
        f"✅ Memória clínica inteligente\n"
        f"✅ Busca em PubMed, SciELO e LILACS\n"
        f"✅ Análise de exames por imagem\n\n"
        f"Use meu link de indicação e ganhe **25% de desconto** no primeiro mês:\n\n"
        f"{link}\n\n"
        f"Vem ser um especialista com o MestreFisio! 🚀"
    )
    bot.send_message(message.chat.id, convite, parse_mode='Markdown')

# =================================================================
# BLOCO 3 - CALLBACKS PRINCIPAIS E FLUXOS (COM NOVAS FUNÇÕES NO SUBMENU PACIENTE)
# =================================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    data = call.data

    if data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    elif data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)

    elif data == "analisar_laudo":
        user_state[call.from_user.id] = {"tipo": "laudo"}
        bot.send_message(call.message.chat.id, "📷 Envie a imagem ou PDF do laudo para análise.")

    # ========== BUSCAR ARTIGOS ==========
    elif data == "buscar_artigos":
        if not pode_usar_recurso(call.from_user.id, "busca"):
            bot.send_message(call.message.chat.id, "🔒 Limite de buscas científicas atingido. Consulte /planos para ampliar.")
            return
        msg = bot.send_message(call.message.chat.id, "🔍 Digite o termo de busca (diagnóstico, condição, etc.) para pesquisar em PubMed, SciELO e LILACS:")
        bot.register_next_step_handler(msg, processar_busca_cientifica)

    elif data == "pacientes":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📋 Todos", callback_data="pacientes_filtro_todos"),
            types.InlineKeyboardButton("🟢 Ativos", callback_data="pacientes_filtro_ativos"),
            types.InlineKeyboardButton("🔴 Alta", callback_data="pacientes_filtro_alta"),
            types.InlineKeyboardButton("🔤 A-Z", callback_data="pacientes_ordem_az"),
            types.InlineKeyboardButton("🔠 Z-A", callback_data="pacientes_ordem_za"),
            types.InlineKeyboardButton("📅 Mais recentes", callback_data="pacientes_ordem_recente"),
            types.InlineKeyboardButton("📅 Mais antigos", callback_data="pacientes_ordem_antigo")
        )
        bot.send_message(call.message.chat.id, "📊 Opções de filtro e ordenação:", reply_markup=markup)

    elif data.startswith("pacientes_filtro_") or data.startswith("pacientes_ordem_"):
        partes = data.split("_")
        tipo = partes[2]
        query = {"profissional_id": call.from_user.id}
        
        if data.startswith("pacientes_filtro_"):
            if tipo == "ativos":
                query["status"] = "ativo"
            elif tipo == "alta":
                query["status"] = "alta"
            user_state[call.from_user.id] = {"filtro": tipo, "ordem": user_state.get(call.from_user.id, {}).get("ordem", "az")}
        else:
            user_state[call.from_user.id] = {"ordem": tipo, "filtro": user_state.get(call.from_user.id, {}).get("filtro", "todos")}
            if user_state[call.from_user.id]["filtro"] == "ativos":
                query["status"] = "ativo"
            elif user_state[call.from_user.id]["filtro"] == "alta":
                query["status"] = "alta"
        
        pacientes = list(pacientes_coll.find(query))
        
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente encontrado.")
            return
        
        ordem = user_state.get(call.from_user.id, {}).get("ordem", "az")
        if ordem == "az":
            pacientes.sort(key=lambda x: x['nome'])
        elif ordem == "za":
            pacientes.sort(key=lambda x: x['nome'], reverse=True)
        elif ordem == "recente":
            pacientes.sort(key=lambda x: x.get('criado_em', ''), reverse=True)
        elif ordem == "antigo":
            pacientes.sort(key=lambda x: x.get('criado_em', ''))
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        for p in pacientes:
            status_emoji = "🟢" if p.get("status", "ativo") == "ativo" else "🔴"
            data_criacao = p.get('criado_em', 'N/A')
            markup.add(types.InlineKeyboardButton(f"{status_emoji} {p['nome']} ({data_criacao})", callback_data=f"paciente_{p['nome']}"))
        
        markup.add(types.InlineKeyboardButton("🔙 Voltar aos filtros", callback_data="pacientes"))
        bot.send_message(call.message.chat.id, "👥 Selecione o paciente:", reply_markup=markup)

    elif data.startswith("paciente_"):
        nome = data.replace("paciente_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if not paciente:
            bot.send_message(call.message.chat.id, "❌ Paciente não encontrado.")
            return
        texto = f"📂 {nome}\n\nStatus: {paciente.get('status', 'ativo').upper()}\nData cadastro: {paciente.get('criado_em', 'N/A')}\nÚltima análise: {paciente.get('data', 'N/A')}\n\n🧠 Última análise:\n{paciente.get('ultima_analise', 'Sem análise anterior.')[:500]}..."
        user_state[call.from_user.id] = {"paciente": nome}
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📈 Evolução diária", callback_data="evolucao_diaria"),
            types.InlineKeyboardButton("🧠 Nova análise", callback_data="nova_analise"),
            types.InlineKeyboardButton("📄 Laudo/Atestado", callback_data=f"gerar_laudo_paciente_{nome}"),
            types.InlineKeyboardButton("📄 Resumo PDF", callback_data=f"pdf_{nome}"),
            types.InlineKeyboardButton("🧠 Educação em Dor", callback_data=f"educacao_dor_{nome}"),
            types.InlineKeyboardButton("🔄 Alterar Status", callback_data=f"alterar_status_{nome}")
        )
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)

    # ========== GERAR LAUDO/ATESTADO DIRETO DO PACIENTE ==========
    elif data.startswith("gerar_laudo_paciente_"):
        nome = data.replace("gerar_laudo_paciente_", "")
        user_state[call.from_user.id] = {"tipo": "laudo_tipo", "paciente": nome}
        markup = types.InlineKeyboardMarkup(row_width=2)
        tipos = [
            ("🧾 Laudo clínico", "clinico"),
            ("🏋️ Exercícios", "exercicios"),
            ("📉 Evolução", "evolucao"),
            ("🛌 Atestado", "atestado"),
            ("⚡ Tratamento", "tratamento"),
            ("📊 Convênio", "convenio"),
            ("🧠 Biomecânica", "biomecanica")
        ]
        for nome_tipo, tipo in tipos:
            markup.add(types.InlineKeyboardButton(nome_tipo, callback_data=f"laudo_tipo_{tipo}_{nome}"))
        bot.send_message(call.message.chat.id, f"Tipo de laudo para {nome}:", reply_markup=markup)

    elif data.startswith("laudo_tipo_"):
        partes = data.split("_")
        tipo = partes[2]
        nome = partes[3]
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if not paciente:
            bot.send_message(call.message.chat.id, "Paciente não encontrado.")
            return
        memoria = montar_memoria_clinica(paciente)
        profissional = uso_coll.find_one({"user_id": call.from_user.id})
        nome_prof = profissional.get("nome_profissional", "Profissional")
        registro = profissional.get("registro_profissional", "")
        especialidade = "Fisioterapeuta PhD Especialista em Ortopedia e Biomecânica"

        prompt_laudo = PROMPTS_LAUDO.get(tipo, PROMPTS_LAUDO["clinico"])
        prompt = f"""
{PROMPT_SISTEMA_COMPLETO}

Paciente: {nome}

Histórico clínico completo:
{memoria}

{prompt_laudo}

Finalize com assinatura profissional.
"""
        analise = chamar_gemini(call.message, prompt, nome, tipo="laudo")
        if analise:
            texto_final = f"""Paciente: {nome}

{analise}

---

**Atenciosamente,**

**{nome_prof}**  
{especialidade}  
Registro: {registro}

---

**Assinatura do Paciente (confirmação de recebimento e compreensão):**

_______________________________________
{paciente.get('nome', nome)}

"""
            pdf_buffer = gerar_pdf(nome, texto_final)
            bot.send_document(call.message.chat.id, pdf_buffer, visible_file_name=f"Laudo_{tipo}_{nome}.pdf")
        else:
            bot.send_message(call.message.chat.id, "❌ Erro ao gerar laudo.")

    # ========== EDUCAÇÃO EM DOR ==========
    elif data.startswith("educacao_dor_"):
        nome = data.replace("educacao_dor_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if not paciente:
            bot.send_message(call.message.chat.id, "Paciente não encontrado.")
            return
        memoria = montar_memoria_clinica(paciente)
        prompt = f"""
Você é um fisioterapeuta especialista em educação em dor. Com base no caso do paciente {nome} e nas informações abaixo, crie um texto educativo para ser entregue ao paciente. O texto deve ser claro, acolhedor e explicar:
- O que é a dor e por que ela ocorre (sem linguagem técnica excessiva)
- Como a fisioterapia pode ajudar
- Dicas práticas para lidar com a dor no dia a dia
- A importância do movimento seguro

Informações do caso:
{memoria[:2000]}

Use uma linguagem empática e motivadora.
"""
        analise = chamar_gemini(call.message, prompt, tipo="analise")
        # Não salvar como análise do paciente, apenas enviar

    elif data.startswith("alterar_status_"):
        nome = data.replace("alterar_status_", "")
        status_atual = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome}).get("status", "ativo")
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 Ativo", callback_data=f"set_status_{nome}_ativo"),
            types.InlineKeyboardButton("🔴 Alta", callback_data=f"set_status_{nome}_alta")
        )
        bot.send_message(call.message.chat.id, f"Status atual: {status_atual.upper()}\nAlterar para:", reply_markup=markup)

    elif data.startswith("set_status_"):
        # formato: "set_status_{nome}_{novo_status}" onde novo_status é "ativo" ou "alta"
        resto = data[len("set_status_"):]
        partes_status = resto.rsplit("_", 1)
        nome, novo_status = partes_status[0], partes_status[1]
        pacientes_coll.update_one(
            {"profissional_id": call.from_user.id, "nome": nome},
            {"$set": {"status": novo_status, "data_alta": datetime.now() if novo_status == "alta" else None}}
        )
        bot.send_message(call.message.chat.id, f"✅ Status de {nome} alterado para {novo_status.upper()}.")
        callback_query(types.CallbackQuery(id=call.id, from_user=call.from_user, message=call.message, data=f"paciente_{nome}"))

    elif data == "evolucao_diaria":
        msg = bot.send_message(call.message.chat.id, "✍️ Envie a evolução do dia:")
        bot.register_next_step_handler(msg, receber_evolucao)

    elif data == "nova_analise":
        nome = user_state.get(call.from_user.id, {}).get("paciente")
        if not nome:
            bot.send_message(call.message.chat.id, "Erro: paciente não identificado.")
            return
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        memoria = montar_memoria_clinica(paciente)
        prompt = f"""
{PROMPT_SISTEMA_COMPLETO}

PACIENTE: {nome}
HISTÓRICO PRÉVIO: {memoria}

Sua tarefa é fornecer uma análise resumida para acompanhamento do caso:
1. RESUMO DO CASO (evolução)
2. PROGNÓSTICO ATUAL
3. CONDUTAS SUGERIDAS (bloco exclusivo)
"""
        chamar_gemini(call.message, prompt, nome, tipo="analise")

    elif data.startswith("pdf_"):
        nome = data.split("_")[1]
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if paciente and paciente.get("ultima_analise"):
            bot.send_message(call.message.chat.id, f"⏳ Gerando PDF de resumo para {nome}...")
            pdf_buffer = gerar_pdf(nome, paciente["ultima_analise"])
            bot.send_document(call.message.chat.id, pdf_buffer, visible_file_name=f"Resumo_Clinico_{nome}.pdf")
        else:
            bot.send_message(call.message.chat.id, "❌ Não encontrei uma análise salva para gerar o resumo.")

    elif data == "metricas_admin":
        if not is_admin(call.from_user.id):
            bot.send_message(call.message.chat.id, "Acesso restrito.")
            return
        total_usuarios = uso_coll.count_documents({})
        total_pacientes = pacientes_coll.count_documents({})
        total_analises = logs_coll.count_documents({})
        bot.send_message(call.message.chat.id, f"📊 MÉTRICAS\n\n👥 Usuários: {total_usuarios}\n🧾 Pacientes: {total_pacientes}\n🧠 Análises: {total_analises}")

    elif data == "planos":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⭐ Prata - R$49,90/mês", callback_data="assinar_prata"),
            types.InlineKeyboardButton("🌟 Ouro - R$69,90/mês", callback_data="assinar_ouro"),
            types.InlineKeyboardButton("💎 Diamante - R$99,90/mês", callback_data="assinar_diamante")
        )
        bot.send_message(call.message.chat.id, "Escolha o plano desejado:", reply_markup=markup)

    elif data.startswith("assinar_"):
        plano = data.split("_")[1]
        precos = {"prata": 4990, "ouro": 6990, "diamante": 9990}
        titulos = {"prata": "Plano Prata", "ouro": "Plano Ouro", "diamante": "Plano Diamante"}
        try:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title=f"MestreFisio PhD - {titulos[plano]}",
                description=f"Acesso a {obter_limites_plano(plano)['analises']} análises mensais e buscas científicas.",
                provider_token=TOKEN_PAYMENT,
                currency="BRL",
                prices=[types.LabeledPrice("Assinatura mensal", precos[plano])],
                invoice_payload=f"plano_{plano}",
                start_parameter=f"plano_{plano}"
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Erro no pagamento:\n{str(e)}")

    elif data == "dashboard":
        # Adapta call.message para ter from_user correto (call.message.from_user é o bot)
        user_id = call.from_user.id
        token = gerar_token_dashboard(user_id)
        link_prof = f"{DOMAIN}/profissional?token={token}"
        bot.send_message(call.message.chat.id, f"🌐 Acesse seu painel profissional (válido por 1h):\n{link_prof}")
        if is_admin(user_id):
            link_admin = f"{DOMAIN}/admin?token={token}"
            bot.send_message(call.message.chat.id, f"👑 Link admin (válido por 1h):\n{link_admin}")

    elif data == "indicar":
        cmd_indicar(call.message)

    # ========== BANCO DE EXERCÍCIOS ==========
    elif data == "banco_exercicios":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for regiao in REGIOES_BANCO:
            markup.add(types.InlineKeyboardButton(regiao, callback_data=f"bex_regiao_{regiao}"))
        markup.add(types.InlineKeyboardButton("🔙 Menu Principal", callback_data="menu"))
        bot.send_message(call.message.chat.id,
            "🏋️ *Banco de Exercícios Terapêuticos*\nSelecione a região corporal:",
            parse_mode='Markdown', reply_markup=markup)

    elif data.startswith("bex_regiao_"):
        regiao = data[len("bex_regiao_"):]
        exercicios = BANCO_EXERCICIOS.get(regiao, [])
        if not exercicios:
            bot.send_message(call.message.chat.id, "Região não encontrada.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for i, ex in enumerate(exercicios):
            markup.add(types.InlineKeyboardButton(
                f"{ex['nivel']} {ex['nome']}", callback_data=f"bex_ex_{regiao}|{i}"))
        markup.add(types.InlineKeyboardButton("🔙 Regiões", callback_data="banco_exercicios"))
        bot.send_message(call.message.chat.id,
            f"📋 *{regiao}* – {len(exercicios)} exercícios disponíveis:\n\nToque para ver detalhes:",
            parse_mode='Markdown', reply_markup=markup)

    elif data.startswith("bex_ex_"):
        resto = data[len("bex_ex_"):]
        partes = resto.rsplit("|", 1)
        if len(partes) != 2:
            bot.send_message(call.message.chat.id, "Erro ao carregar exercício.")
            return
        regiao, idx_str = partes
        try:
            idx = int(idx_str)
        except ValueError:
            bot.send_message(call.message.chat.id, "Erro ao carregar exercício.")
            return
        exercicios = BANCO_EXERCICIOS.get(regiao, [])
        if idx < 0 or idx >= len(exercicios):
            bot.send_message(call.message.chat.id, "Exercício não encontrado.")
            return
        ex = exercicios[idx]
        texto = formatar_exercicio(ex)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(f"🔙 Voltar a {regiao}", callback_data=f"bex_regiao_{regiao}"))
        bot.send_message(call.message.chat.id, texto, parse_mode='Markdown', reply_markup=markup)

    elif data == "menu":
        bot.send_message(call.message.chat.id, "📋 Menu principal:", reply_markup=menu_principal())

    else:
        bot.send_message(call.message.chat.id, f"⚠️ Comando não reconhecido.")

# ================= FUNÇÃO PARA PROCESSAR BUSCA CIENTÍFICA =================
def processar_busca_cientifica(message):
    query = (message.text or "").strip()[:300]
    if not query:
        bot.send_message(message.chat.id, "❌ Por favor, informe um termo de busca válido.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🔍 Buscando evidências em PubMed, SciELO e LILACS...\nIsso pode levar alguns segundos.")

    artigos = buscar_todas_fontes(query)
    if not artigos:
        bot.edit_message_text("Nenhum artigo encontrado.", chat_id=message.chat.id, message_id=aguarde.message_id)
        return

    # Monta mensagem com os artigos e links
    texto = f"*📚 Evidências para: {query}*\n\n"
    for i, art in enumerate(artigos, 1):
        texto += f"*{i}. {art['titulo']}*\n"
        texto += f"📌 *Fonte:* {art['fonte']}\n"
        texto += f"📄 {art['resumo'][:400]}...\n"
        if art['link']:
            texto += f"🔗 [Ler artigo completo]({art['link']})\n"
        texto += "\n"
        if len(texto) > 3800:  # limite do Telegram
            texto += "\n... (mais artigos não listados)"
            break

    bot.edit_message_text(texto, chat_id=message.chat.id, message_id=aguarde.message_id, parse_mode='Markdown', disable_web_page_preview=True)

    # Gera síntese com IA
    bot.send_message(message.chat.id, "🤖 Gerando síntese dos achados...")
    sintese = sintetizar_artigos_com_ia(query, artigos)
    bot.send_message(message.chat.id, f"📝 *Síntese das evidências:*\n\n{sintese}", parse_mode='Markdown', reply_markup=menu_principal())

# =================================================================
# BLOCO 4 - FUNÇÕES DE FLUXO, ARQUIVOS, PAGAMENTOS E EXECUÇÃO
# =================================================================

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    if not nome or len(nome) < 2:
        msg = bot.send_message(message.chat.id, "❌ Nome inválido. Digite o nome completo do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
        return
    if len(nome) > 120:
        msg = bot.send_message(message.chat.id, "❌ Nome muito longo (máx. 120 caracteres). Digite novamente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
        return
    # Verifica limite de pacientes do plano
    user = uso_coll.find_one({"user_id": message.from_user.id})
    if user and not is_admin(message.from_user.id):
        plano = user.get("plano", "gratuito") if user.get("pro") else "gratuito"
        limite_pac = obter_limites_plano(plano)["pacientes"]
        total_pac = pacientes_coll.count_documents({"profissional_id": message.from_user.id})
        if total_pac >= limite_pac:
            bot.send_message(message.chat.id, f"🚫 Limite de {limite_pac} pacientes atingido no plano {plano.capitalize()}. Faça upgrade em /planos.", reply_markup=menu_principal())
            return
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$setOnInsert": {"status": "ativo", "criado_em": datetime.now()}},
        upsert=True
    )
    with _state_lock:
        user_state[message.from_user.id] = {"tipo": "novo_paciente", "paciente": nome}
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico (máx. {MAX_INPUT_LEN} caracteres):")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    texto_clinico = (message.text or "").strip()[:MAX_INPUT_LEN]
    if not texto_clinico:
        bot.send_message(message.chat.id, "❌ Descrição vazia. Tente novamente.", reply_markup=menu_principal())
        return
    paciente = pacientes_coll.find_one({"profissional_id": message.from_user.id, "nome": nome}) or {}
    memoria = montar_memoria_clinica(paciente)
    prompt = f"""
{PROMPT_SISTEMA_COMPLETO}

PACIENTE: {nome}
INFORMAÇÕES CLÍNICAS: {texto_clinico}

Sua tarefa é fornecer uma análise para este novo paciente:
1. RESUMO DO CASO (com base nas informações fornecidas)
2. PROGNÓSTICO (expectativa de evolução)
3. CONDUTAS SUGERIDAS (bloco exclusivo)

Seja direto, técnico e estruture a resposta em tópicos.
"""
    chamar_gemini(message, prompt, nome, tipo="analise")

def processar_ia_direta(message):
    pergunta = (message.text or "").strip()[:MAX_INPUT_LEN]
    if not pergunta:
        bot.send_message(message.chat.id, "❌ Nenhuma dúvida informada.", reply_markup=menu_principal())
        return
    prompt = f"{PROMPT_DUVIDA_TECNICA}\n\nPergunta: {pergunta}"
    chamar_gemini(message, prompt, tipo="analise")

def receber_evolucao(message):
    with _state_lock:
        nome = user_state.get(message.from_user.id, {}).get("paciente")
    if not nome:
        bot.send_message(message.chat.id, "Erro: paciente não identificado.", reply_markup=menu_principal())
        return
    nota = (message.text or "").strip()[:MAX_INPUT_LEN]
    if not nota:
        bot.send_message(message.chat.id, "❌ Evolução vazia. Tente novamente.", reply_markup=menu_principal())
        return
    data_hora = datetime.now().strftime('%d/%m/%Y %H:%M')
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$push": {"historico_evolucao": {"data": data_hora, "nota": nota}}},
        upsert=True
    )
    bot.send_message(message.chat.id, f"✅ Evolução registrada em {data_hora}.")
    paciente = pacientes_coll.find_one({"profissional_id": message.from_user.id, "nome": nome})
    memoria = montar_memoria_clinica(paciente)
    prompt = f"""
{PROMPT_SISTEMA_COMPLETO}

Paciente: {nome}
Histórico:
{memoria}
Nova evolução: {nota}

Forneça uma análise resumida considerando essa evolução:
1. EVOLUÇÃO CLÍNICA
2. AJUSTES NA CONDUTA
3. PRÓXIMOS PASSOS
"""
    chamar_gemini(message, prompt, nome, tipo="analise")

@bot.message_handler(content_types=['photo', 'document'])
def receber_arquivo(message):
    with _state_lock:
        estado = user_state.get(message.from_user.id)
    if not estado or estado.get("tipo") != "laudo":
        return
    bot.send_message(message.chat.id, "🔍 Processando laudo...")
    try:
        if message.document:
            file_info = bot.get_file(message.document.file_id)
        else:
            file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        if len(downloaded) > MAX_FILE_SIZE:
            bot.send_message(message.chat.id, f"❌ Arquivo muito grande. Máximo permitido: {MAX_FILE_SIZE // (1024*1024)} MB.")
            return
        texto = extrair_texto_arquivo(downloaded)
        if not texto or texto.startswith("Erro OCR"):
            bot.send_message(message.chat.id, "❌ Não foi possível extrair texto do laudo. Certifique-se de enviar uma imagem nítida.")
            return
        prompt = f"{PROMPT_SISTEMA_COMPLETO}\n\nAnalise o seguinte laudo médico:\n\n{texto[:4000]}"
        chamar_gemini(message, prompt, tipo="analise")
    except Exception as e:
        logger.error(f"Erro ao processar arquivo: {e}")
        bot.send_message(message.chat.id, "❌ Erro ao processar o arquivo. Tente novamente.")
    finally:
        with _state_lock:
            user_state.pop(message.from_user.id, None)

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    plano = payload.split("_")[1] if payload.startswith("plano_") else "prata"

    user = uso_coll.find_one({"user_id": user_id})
    desconto = user.get("creditos_desconto", 0)
    valor_original = {"prata": 4990, "ouro": 6990, "diamante": 9990}[plano]
    if desconto > 0:
        desconto_aplicado = min(desconto, 50)
        valor_pago = int(valor_original * (1 - desconto_aplicado/100))
        uso_coll.update_one({"_id": user["_id"]}, {"$set": {"creditos_desconto": 0}})
        bot.send_message(message.chat.id, f"🎉 Desconto de {desconto_aplicado}% aplicado! Valor pago: R$ {valor_pago/100:.2f}")

    uso_coll.update_one(
        {"user_id": user_id},
        {"$set": {
            "pro": True,
            "plano": plano,
            "pro_expira_em": time.time() + 30*24*60*60,
            "uso_mes": 0,
            "laudos_mes": 0,
            "uso_buscas": 0,
            "ultimo_reset": datetime.now()
        }},
        upsert=True
    )
    limites = obter_limites_plano(plano)
    bot.send_message(message.chat.id, f"💎 Pagamento aprovado! Plano {plano.capitalize()} ativo por 30 dias 🚀\n\n✅ {limites['analises']} análises/mês\n✅ {limites['laudos']} laudos/mês\n✅ {limites['buscas']} buscas científicas/mês")

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(2)
    logger.info("Bot MestreFisio iniciado com sucesso.")
    while True:
        try:
            bot.infinity_polling(timeout=120, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot polling interrompido: {e}. Reiniciando em 10s...")
            time.sleep(10)
