# =================================================================
# BLOCO 1 - INSTALAÇÃO DE DEPENDÊNCIAS, IMPORTS, CONFIGURAÇÕES, BANCO E BUSCAS
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
            print(f"Instalando {pacote}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pacote])

instalar_pacotes()

import os
import io
import time
import threading
import random
import string
from datetime import datetime, timedelta

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

if not TOKEN_TELEGRAM:
    raise ValueError("TOKEN_TELEGRAM não definido")
if not MONGO_URI:
    raise ValueError("MONGO_URI não definido")
if not API_KEY_IA:
    raise ValueError("API_KEY_IA não definido")

# ================= BANCO DE DADOS =================
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
uso_coll = db['uso_usuarios']
logs_coll = db['logs_analises']

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
                novo_credito = indicador.get("creditos_desconto", 0) + 25
                uso_coll.update_one({"_id": indicador["_id"]}, {"$set": {"creditos_desconto": novo_credito}})
                uso_coll.update_one({"_id": indicador["_id"]}, {"$push": {"indicacoes": {"user_id": user_id, "data": datetime.now()}}})
                try:
                    bot = telebot.TeleBot(TOKEN_TELEGRAM)
                    bot.send_message(indicador["user_id"], f"🎉 Parabéns! Um novo profissional se cadastrou usando seu código. Você ganhou +25% de desconto na próxima mensalidade! Seu saldo atual: {novo_credito}%")
                except:
                    pass

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
                bot = telebot.TeleBot(TOKEN_TELEGRAM)
                bot.send_message(ADMIN_ID, f"🚀 Novo usuário: ID {user_id}")
            except:
                pass

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

def extrair_texto_arquivo(file_bytes):
    try:
        imagem = Image.open(io.BytesIO(file_bytes))
        texto = pytesseract.image_to_string(imagem, lang='por')
        return texto.strip()
    except Exception as e:
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
        print(f"Erro PubMed: {e}")
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
        print(f"Erro SciELO: {e}")
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
        print(f"Erro LILACS: {e}")
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
        print(f"Erro síntese IA: {e}")
        return "Erro ao gerar síntese."

# ================= SERVIDOR FLASK =================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chave_secreta_temporaria")

@app.route('/')
def home():
    return "MestreFisio V5.0 - Servidor Ativo 🧠"

@app.route('/admin')
def admin_dashboard():
    user_id = request.args.get('user_id')
    if not user_id or not is_admin(int(user_id)):
        return "Acesso negado", 403
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
    user_id = request.args.get('user_id')
    if not user_id:
        return "Identifique-se com ?user_id=123", 400
    user_id = int(user_id)
    profissional = uso_coll.find_one({"user_id": user_id})
    if not profissional:
        return "Profissional não encontrado", 404
    pacientes = list(pacientes_coll.find({"profissional_id": user_id}).sort("criado_em", -1))
    return render_template_string(PROFISSIONAL_TEMPLATE,
                                  profissional=profissional,
                                  pacientes=pacientes,
                                  admin_id=ADMIN_ID)

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html><head><title>Dashboard Admin</title></head>
<body>
<h1>Painel Administrativo</h1>
<p>Total usuários: {{ total_usuarios }}</p>
<p>Total pacientes: {{ total_pacientes }}</p>
<p>Total análises: {{ total_analises }}</p>
<h2>Últimos usuários</h2>
<ul>
{% for u in ultimos_usuarios %}
    <li>ID: {{ u.user_id }} - Plano: {{ u.plano }} - PRO: {{ u.pro }}</li>
{% endfor %}
</ul>
</body>
</html>
"""

PROFISSIONAL_TEMPLATE = """
<!DOCTYPE html>
<html><head><title>Dashboard Profissional</title></head>
<body>
<h1>Olá, {{ profissional.nome_profissional or profissional.user_id }}</h1>
<p>Registro: {{ profissional.registro_profissional or "Não informado" }}</p>
<p>Plano atual:
{% if profissional.user_id == admin_id %}ADMINISTRADOR
{% elif profissional.plano == "prata" %}⭐ Prata (30 consultas/mês)
{% elif profissional.plano == "ouro" %}🌟 Ouro (60 consultas/mês)
{% elif profissional.plano == "diamante" %}💎 Diamante (300 consultas/mês)
{% else %}🚀 Gratuito (5 consultas/mês)
{% endif %}
</p>
<h2>Seus Pacientes ({{ pacientes|length }})</h2>
<ul>
{% for p in pacientes %}
    <li><strong>{{ p.nome }}</strong> - Status: {{ p.status or "ativo" }} - Criado: {{ p.criado_em or "N/A" }}</li>
{% endfor %}
</ul>
</body>
</html>
"""

def run_flask():
    app.run(host='0.0.0.0', port=10000)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# =================================================================
# BLOCO 2 - BOT, PROMPTS, MENU, HANDLERS E COMANDOS
# =================================================================

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
user_state = {}

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
    "exercicios": "Gere um programa de exercícios terapêuticos detalhado, mas conciso (máximo 1 página). Liste: 1) Objetivos, 2) Exercícios (nome, execução, séries/repetições), 3) Frequência e cuidados.",
    "evolucao": "Gere um relato de evolução clínica objetiva (máximo 1 página). Inclua: 1) Resumo da evolução, 2) Comparação com avaliação anterior, 3) Ajustes na conduta, 4) Metas.",
    "atestado": "Gere um atestado médico profissional (máximo 1 página). Inclua: 1) Identificação do paciente, 2) Período de afastamento (se aplicável), 3) CID e justificativa, 4) Recomendações. Formato oficial.",
    "tratamento": "Gere um plano de tratamento estruturado (máximo 1 página). Inclua: 1) Objetivos de curto/médio/longo prazo, 2) Modalidades terapêuticas, 3) Cronograma, 4) Critérios de alta.",
    "convenio": "Gere um relatório para convênio (máximo 1 página). Inclua: 1) Diagnóstico, 2) Evolução, 3) Sessões realizadas, 4) Resultados alcançados, 5) Necessidade de continuidade.",
    "biomecanica": "Gere uma análise biomecânica funcional (máximo 1 página). Inclua: 1) Análise de cadeia cinética, 2) Compensações observadas, 3) Estratégias de correção, 4) Exercícios específicos."
}

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
            print(response.text)
            return None
        res_data = response.json()
        try:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
        except:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "⚠️ Erro ao interpretar resposta da IA.")
            print(res_data)
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
        print(e)
        bot.send_message(message.chat.id, "❌ Erro na IA.")
        return None

# ================= MENU PRINCIPAL =================
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("👥 Pacientes", callback_data="pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("📷 Analisar Laudo", callback_data="analisar_laudo"),
        types.InlineKeyboardButton("📄 Gerar Laudo/Atestado", callback_data="gerar_laudo"),
        types.InlineKeyboardButton("🔍 Buscar Artigos", callback_data="buscar_artigos"),
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
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.0 Especialista**\nAgora com memória clínica inteligente.", reply_markup=menu_principal())

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
        partes = message.text.split('|')
        if len(partes) < 2:
            raise ValueError
        nome = partes[0].strip()
        registro = partes[1].strip()
        uso_coll.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"nome_profissional": nome, "registro_profissional": registro}}
        )
        bot.send_message(message.chat.id, f"✅ Dados salvos:\n👤 {nome}\n🆔 {registro}\n\nAgora você pode usar todas as funcionalidades!", reply_markup=menu_principal())
    except:
        bot.send_message(message.chat.id, "❌ Formato inválido. Use exatamente:\n`Nome Completo | Crefito 123456`\nTente novamente.")
        verificar_dados_profissional(message)

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
🔹 *Gerar Laudo/Atestado* – Escolha paciente e tipo de documento para emitir.
🔹 *Buscar Artigos* – Pesquise evidências em PubMed, SciELO e LILACS e receba uma síntese.
🔹 *Planos Pagos* – Assine um dos planos (Prata, Ouro, Diamante) com acesso ampliado.
🔹 *Dashboard* – Acesse seu painel profissional online.
🔹 *Indique um colega* – Ganhe descontos ao indicar outros profissionais.

Comandos rápidos:
/historico – Lista pacientes
/planos – Detalhes dos planos
/ajuda – Este texto
/dashboard – Link para painel
/indicar – Gerar link de indicação
"""
    bot.send_message(message.chat.id, ajuda_texto, parse_mode='Markdown')

@bot.message_handler(commands=['consulta'])
def cmd_consulta(message):
    msg = bot.send_message(message.chat.id, "💡 Qual condição deseja analisar hoje?")
    bot.register_next_step_handler(msg, processar_ia_direta)

@bot.message_handler(commands=['dashboard'])
def cmd_dashboard(message):
    user_id = message.from_user.id
    dominio = "https://fisio-ia-bot-1.onrender.com"  # DOMÍNIO CORRIGIDO
    link_prof = f"{dominio}/profissional?user_id={user_id}"
    bot.send_message(message.chat.id, f"🌐 Acesse seu painel profissional aqui:\n{link_prof}")
    if is_admin(user_id):
        link_admin = f"{dominio}/admin?user_id={user_id}"
        bot.send_message(message.chat.id, f"👑 Link admin:\n{link_admin}")

@bot.message_handler(commands=['indicar'])
def cmd_indicar(message):
    user = uso_coll.find_one({"user_id": message.from_user.id})
    if not user:
        registrar_usuario_se_novo(message.from_user.id)
        user = uso_coll.find_one({"user_id": message.from_user.id})
    codigo = user.get("codigo_indicacao")
    link = f"https://t.me/{bot.get_me().username}?start={codigo}"

    # Mensagem 1: explicação do sistema de indicação
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

    # Mensagem 2: texto para copiar e enviar ao amigo
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
# BLOCO 3 - CALLBACKS PRINCIPAIS E FLUXOS (COM BUSCA DE ARTIGOS E STATUS CORRIGIDOS)
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

    elif data == "gerar_laudo":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"laudo_sel_paciente_{p['nome']}"))
        bot.send_message(call.message.chat.id, "Selecione o paciente para gerar laudo/atestado:", reply_markup=markup)

    elif data.startswith("laudo_sel_paciente_"):
        nome = data.replace("laudo_sel_paciente_", "")
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
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📈 Evolução diária", callback_data="evolucao_diaria"),
            types.InlineKeyboardButton("🧠 Nova análise", callback_data="nova_analise"),
            types.InlineKeyboardButton("📄 Gerar Laudo PDF", callback_data=f"pdf_{nome}"),
            types.InlineKeyboardButton("🔄 Alterar Status", callback_data=f"alterar_status_{nome}")
        )
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)

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
        _, nome, novo_status = data.split("_")
        pacientes_coll.update_one(
            {"profissional_id": call.from_user.id, "nome": nome},
            {"$set": {"status": novo_status, "data_alta": datetime.now() if novo_status == "alta" else None}}
        )
        bot.send_message(call.message.chat.id, f"✅ Status de {nome} alterado para {novo_status.upper()}.")
        # Volta ao submenu do paciente
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
        cmd_dashboard(call.message)

    elif data == "indicar":
        cmd_indicar(call.message)

    else:
        bot.send_message(call.message.chat.id, f"⚠️ Comando não reconhecido.")

# ================= FUNÇÃO PARA PROCESSAR BUSCA CIENTÍFICA =================
def processar_busca_cientifica(message):
    query = message.text.strip()
    if not query:
        bot.send_message(message.chat.id, "Por favor, informe um termo válido.")
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
    bot.send_message(message.chat.id, f"📝 *Síntese das evidências:*\n\n{sintese}", parse_mode='Markdown')

# =================================================================
# BLOCO 4 - FUNÇÕES DE FLUXO, ARQUIVOS, PAGAMENTOS E EXECUÇÃO
# =================================================================

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$setOnInsert": {"status": "ativo", "criado_em": datetime.now()}},
        upsert=True
    )
    user_state[message.from_user.id] = {"tipo": "novo_paciente", "paciente": nome}
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    paciente = pacientes_coll.find_one({"profissional_id": message.from_user.id, "nome": nome}) or {}
    memoria = montar_memoria_clinica(paciente)
    prompt = f"""
{PROMPT_SISTEMA_COMPLETO}

PACIENTE: {nome}
INFORMAÇÕES CLÍNICAS: {message.text}

Sua tarefa é fornecer uma análise para este novo paciente:
1. RESUMO DO CASO (com base nas informações fornecidas)
2. PROGNÓSTICO (expectativa de evolução)
3. CONDUTAS SUGERIDAS (bloco exclusivo)

Seja direto, técnico e estruture a resposta em tópicos.
"""
    chamar_gemini(message, prompt, nome, tipo="analise")

def processar_ia_direta(message):
    prompt = f"{PROMPT_DUVIDA_TECNICA}\n\nPergunta: {message.text}"
    chamar_gemini(message, prompt, tipo="analise")

def receber_evolucao(message):
    nome = user_state.get(message.from_user.id, {}).get("paciente")
    if not nome:
        bot.send_message(message.chat.id, "Erro: paciente não identificado.")
        return
    data_hora = datetime.now().strftime('%d/%m/%Y %H:%M')
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$push": {"historico_evolucao": {"data": data_hora, "nota": message.text}}},
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
Nova evolução: {message.text}

Forneça uma análise resumida considerando essa evolução:
1. EVOLUÇÃO CLÍNICA
2. AJUSTES NA CONDUTA
3. PRÓXIMOS PASSOS
"""
    chamar_gemini(message, prompt, nome, tipo="analise")

@bot.message_handler(content_types=['photo', 'document'])
def receber_arquivo(message):
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
        texto = extrair_texto_arquivo(downloaded)
        if not texto:
            bot.send_message(message.chat.id, "❌ Não foi possível extrair texto do laudo.")
            return
        prompt = f"{PROMPT_SISTEMA_COMPLETO}\n\nAnalise o seguinte laudo médico:\n\n{texto}"
        chamar_gemini(message, prompt, tipo="analise")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro: {str(e)}")
    finally:
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
    print("Bot iniciado...")
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
