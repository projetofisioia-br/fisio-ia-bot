# =================================================================
# BLOCO 1 - IMPORTS, CONFIGURAÇÕES, BANCO E DASHBOARDS
# =================================================================

import os
import io
import time
import threading
import random
import string
from datetime import datetime

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

# Validações
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
    """Gera um código único de 6 caracteres alfanuméricos"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def registrar_usuario_se_novo(user_id, codigo_indicador=None):
    if is_admin(user_id):
        return
    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        # Se veio com código de indicação, creditar desconto ao indicador
        if codigo_indicador:
            indicador = uso_coll.find_one({"codigo_indicacao": codigo_indicador})
            if indicador and indicador["user_id"] != user_id:
                # Adiciona 25% de crédito (até 50% por mês, mas vamos acumular)
                novo_credito = indicador.get("creditos_desconto", 0) + 25
                uso_coll.update_one(
                    {"_id": indicador["_id"]},
                    {"$set": {"creditos_desconto": novo_credito}}
                )
                # Registrar a indicação
                uso_coll.update_one(
                    {"_id": indicador["_id"]},
                    {"$push": {"indicacoes": {"user_id": user_id, "data": datetime.now()}}}
                )
                # Notificar o indicador (opcional)
                try:
                    bot = telebot.TeleBot(TOKEN_TELEGRAM)
                    bot.send_message(indicador["user_id"], f"🎉 Parabéns! Um novo profissional se cadastrou usando seu código. Você ganhou +25% de desconto na próxima mensalidade! Seu saldo atual: {novo_credito}%")
                except:
                    pass

        uso_coll.insert_one({
            "user_id": user_id,
            "uso": 0,
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "pro": False,
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
            uso_coll.update_one({"_id": user["_id"]}, {"$set": {"pro": False}})
            return False
        return True
    return False

def pode_usar(user_id):
    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        registrar_usuario_se_novo(user_id)
        return True

    if verificar_assinatura(user):
        return True

    uso_atual = user.get("uso", 0)
    LIMITE_GRATUITO = 5
    if uso_atual >= LIMITE_GRATUITO:
        return False

    uso_coll.update_one({"_id": user["_id"]}, {"$inc": {"uso": 1}})
    if (uso_atual + 1) >= LIMITE_GRATUITO and ADMIN_ID:
        try:
            bot = telebot.TeleBot(TOKEN_TELEGRAM)
            bot.send_message(ADMIN_ID, f"⚠️ Usuário atingiu limite: ID {user_id}")
        except:
            pass
    return True

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

# ================= SERVIDOR FLASK (DASHBOARDS) =================
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
    pacientes = list(pacientes_coll.find({"profissional_id": user_id}).sort("data", -1))
    return render_template_string(PROFISSIONAL_TEMPLATE,
                                  profissional=profissional,
                                  pacientes=pacientes)

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Dashboard Admin</title></head>
<body>
<h1>Painel Administrativo</h1>
<p>Total usuários: {{ total_usuarios }}</p>
<p>Total pacientes: {{ total_pacientes }}</p>
<p>Total análises: {{ total_analises }}</p>
<h2>Últimos usuários</h2>
<ul>
{% for u in ultimos_usuarios %}
    <li>ID: {{ u.user_id }} - Criado em: {{ u.criado_em }} - PRO: {{ u.pro }}</li>
{% endfor %}
</ul>
</body>
</html>
"""

PROFISSIONAL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Dashboard Profissional</title></head>
<body>
<h1>Olá, {{ profissional.nome_profissional or profissional.user_id }}</h1>
<p>Registro: {{ profissional.registro_profissional or "Não informado" }}</p>
<p>Status: {% if profissional.pro %}PRO Ativo{% else %}Plano Gratuito ({{ profissional.uso }} de 5 usos){% endif %}</p>

<h2>Seus Pacientes</h2>
<ul>
{% for p in pacientes %}
    <li><strong>{{ p.nome }}</strong> - Última análise: {{ p.data or "N/A" }} - Status: {{ p.status or "ativo" }}</li>
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
# BLOCO 2 - BOT TELEGRAM, HANDLERS, FLUXOS CLÍNICOS E INDICAÇÃO
# =================================================================

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
user_state = {}

# ================= PROMPT SISTEMA PRINCIPAL (para análises) =================
PROMPT_SISTEMA = """
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

# ================= PROMPTS PARA LAUDOS (DIRETOS) =================
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
def chamar_gemini(message, prompt, nome_paciente=None):
    if not is_admin(message.from_user.id):
        registrar_usuario_se_novo(message.from_user.id)
        if not pode_usar(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 Limite de análises gratuitas atingido. Considere o plano PRO.")
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

        if nome_paciente:
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
        types.InlineKeyboardButton("💰 Planos Pagos", callback_data="planos"),
        types.InlineKeyboardButton("🌐 Dashboard", callback_data="dashboard"),  # NOVO
        types.InlineKeyboardButton("🎁 Indique um colega", callback_data="indicar")  # NOVO
    )
    if ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Métricas (Admin)", callback_data="metricas_admin"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Verifica se veio com parâmetro de indicação
    args = message.text.split()
    codigo = args[1] if len(args) > 1 else None
    registrar_usuario_se_novo(message.from_user.id, codigo)
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.0 Especialista**\nAgora com memória clínica inteligente.", reply_markup=menu_principal())

# ================= HANDLERS DOS NOVOS COMANDOS =================
@bot.message_handler(commands=['historico'])
def cmd_historico(message):
    # Redireciona para a lista de pacientes (submenu "Pacientes")
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
    # Mostra informações sobre planos
    bot.send_message(message.chat.id, "💎 **Planos disponíveis**\n\nGratuito: 5 análises por mês.\nPRO: acesso ilimitado, R$ 59,90/mês.\n\nPara assinar, use o botão 'Planos Pagos' no menu.", reply_markup=menu_principal())

@bot.message_handler(commands=['ajuda'])
def cmd_ajuda(message):
    ajuda_texto = """
📘 **Ajuda – MestreFisio V5.0**

🔹 *Novo Paciente* – Cadastre um paciente e faça a primeira análise.
🔹 *Pacientes* – Veja lista, histórico, evolua ou gere laudos.
🔹 *Dúvida Técnica* – Tire dúvidas clínicas diretamente com a IA.
🔹 *Analisar Laudo* – Envie imagem/PDF de laudos médicos para interpretação.
🔹 *Gerar Laudo/Atestado* – Escolha paciente e tipo de documento para emitir.
🔹 *Planos Pagos* – Assine o plano PRO com acesso ilimitado.
🔹 *Dashboard* – Acesse seu painel profissional online.
🔹 *Indique um colega* – Ganhe descontos ao indicar outros profissionais.

Comandos rápidos:
/historico – Lista pacientes
/planos – Detalhes dos planos
/ajuda – Este texto
/dashboard – Link para painel
/indicar – Gerar link de indicação

Dúvidas? Fale com o suporte: @seudominio
"""
    bot.send_message(message.chat.id, ajuda_texto, parse_mode='Markdown')

@bot.message_handler(commands=['consulta'])
def cmd_consulta(message):
    # Inicia fluxo de dúvida técnica
    msg = bot.send_message(message.chat.id, "💡 Qual condição deseja analisar hoje?")
    bot.register_next_step_handler(msg, processar_ia_direta)

@bot.message_handler(commands=['dashboard'])
def cmd_dashboard(message):
    user_id = message.from_user.id
    dominio = "https://fisio-ia-bot-1.onrender.com"
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
    texto_convite = (
        f"🎁 *Convide um colega e ganhe descontos!*\n\n"
        f"Compartilhe o link abaixo com profissionais da área. "
        f"Cada novo cadastro com seu código lhe dá **25% de desconto** na próxima mensalidade. "
        f"O desconto pode acumular até 50% por mês, e o saldo não utilizado fica para meses futuros.\n\n"
        f"🔗 Link de indicação:\n"
        f"`https://t.me/{bot.get_me().username}?start={codigo}`\n\n"
        f"Quanto mais indicar, mais desconto! 🚀"
    )
    bot.send_message(message.chat.id, texto_convite, parse_mode='Markdown')

# ================= CALLBACKS =================
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

        # Usa prompt específico para o tipo de laudo
        prompt_laudo = PROMPTS_LAUDO.get(tipo, PROMPTS_LAUDO["clinico"])
        prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico completo:
{memoria}

{prompt_laudo}

Finalize com assinatura profissional (nome, registro) e espaço para assinatura física/digital.
"""
        analise = chamar_gemini(call.message, prompt, nome)
        if analise:
            texto_final = f"Paciente: {nome}\n\n{analise}\n\n---\nProfissional responsável:\n{nome_prof}\nRegistro: {registro}\n\n_________________________\nAssinatura"
            pdf_buffer = gerar_pdf(nome, texto_final)
            bot.send_document(call.message.chat.id, pdf_buffer, visible_file_name=f"Laudo_{tipo}_{nome}.pdf")
        else:
            bot.send_message(call.message.chat.id, "❌ Erro ao gerar laudo.")

    elif data == "pacientes":
        # Filtro de status
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("Todos", callback_data="pacientes_filtro_todos"),
            types.InlineKeyboardButton("Ativos", callback_data="pacientes_filtro_ativos"),
            types.InlineKeyboardButton("Alta", callback_data="pacientes_filtro_alta")
        )
        bot.send_message(call.message.chat.id, "Filtrar pacientes por status:", reply_markup=markup)

    elif data.startswith("pacientes_filtro_"):
        filtro = data.split("_")[-1]
        query = {"profissional_id": call.from_user.id}
        if filtro == "ativos":
            query["status"] = "ativo"
        elif filtro == "alta":
            query["status"] = "alta"
        # "todos" não adiciona filtro
        pacientes = list(pacientes_coll.find(query))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente encontrado.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for p in pacientes:
            status_emoji = "🟢" if p.get("status", "ativo") == "ativo" else "🔴"
            markup.add(types.InlineKeyboardButton(f"{status_emoji} {p['nome']}", callback_data=f"paciente_{p['nome']}"))
        bot.send_message(call.message.chat.id, "👥 Selecione o paciente:", reply_markup=markup)

    elif data.startswith("paciente_"):
        nome = data.replace("paciente_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if not paciente:
            bot.send_message(call.message.chat.id, "❌ Paciente não encontrado.")
            return
        texto = f"📂 {nome}\n\nStatus: {paciente.get('status', 'ativo').upper()}\n\n🧠 Última análise:\n{paciente.get('ultima_analise', 'Sem análise anterior.')[:500]}..."
        user_state[call.from_user.id] = {"paciente": nome}
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📈 Evolução diária", callback_data="evolucao_diaria"),
            types.InlineKeyboardButton("🧠 Nova análise", callback_data="nova_analise"),
            types.InlineKeyboardButton("📄 Gerar Laudo PDF", callback_data=f"pdf_{nome}"),
            types.InlineKeyboardButton("🔄 Alterar Status", callback_data=f"alterar_status_{nome}")  # NOVO
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
        prompt = f"{PROMPT_SISTEMA}\n\nPACIENTE: {nome}\nHISTÓRICO:\n{memoria}\n\nFaça uma análise resumida do caso atual e sugira próximas condutas."
        chamar_gemini(call.message, prompt, nome)

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
        try:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title="MestreFisio PhD Pro 💎",
                description="Acesso ilimitado às análises.",
                provider_token=TOKEN_PAYMENT,
                currency="BRL",
                prices=[types.LabeledPrice("Assinatura Pro", 5990)],
                invoice_payload="pro_access",
                start_parameter="pro_access"
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Erro no pagamento:\n{str(e)}")

    elif data == "dashboard":
        cmd_dashboard(call.message)

    elif data == "indicar":
        cmd_indicar(call.message)

    else:
        bot.send_message(call.message.chat.id, f"⚠️ Comando não reconhecido.")

# ================= FUNÇÕES DE FLUXO =================
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    # Cria paciente com status padrão "ativo"
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
{PROMPT_SISTEMA}

PACIENTE: {nome}
HISTÓRICO PRÉVIO: {memoria}
DADO ATUAL: {message.text}

Sua tarefa é fornecer uma NOVA ANÁLISE RESUMIDA:
1. RESUMO DO CASO: (Máximo 5 linhas sobre o estado atual).
2. EVOLUÇÃO: (O que melhorou ou piorou comparado ao histórico).
3. SUGESTÕES DE PRÓXIMAS CONDUTAS: (Liste 3 condutas práticas e imediatas).

Seja direto, técnico e evite repetições desnecessárias.
"""
    chamar_gemini(message, prompt, nome)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\n{message.text}"
    chamar_gemini(message, prompt)

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
    prompt = f"{PROMPT_SISTEMA}\n\nPaciente: {nome}\nHistórico:\n{memoria}\nNova evolução: {message.text}\n\nFaça uma análise resumida e sugestões."
    chamar_gemini(message, prompt, nome)

# ================= HANDLER DE ARQUIVOS (LAUDOS) =================
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
        prompt = f"{PROMPT_SISTEMA}\n\nAnalise o seguinte laudo médico:\n\n{texto}"
        chamar_gemini(message, prompt)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro: {str(e)}")
    finally:
        user_state.pop(message.from_user.id, None)

# ================= PAGAMENTOS =================
@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(message):
    user_id = message.from_user.id
    user = uso_coll.find_one({"user_id": user_id})
    # Aplica desconto acumulado
    desconto = user.get("creditos_desconto", 0)
    valor_final = 5990  # R$ 59,90 em centavos
    if desconto > 0:
        # Desconto máximo 50%
        desconto_aplicado = min(desconto, 50)
        valor_final = int(valor_final * (1 - desconto_aplicado/100))
        # Zera o saldo de desconto após aplicar
        uso_coll.update_one({"_id": user["_id"]}, {"$set": {"creditos_desconto": 0}})
        bot.send_message(message.chat.id, f"🎉 Desconto de {desconto_aplicado}% aplicado! Valor pago: R$ {valor_final/100:.2f}")
    # Aqui normalmente você integraria com o gateway de pagamento. O Telegram já processou, então apenas ativamos o PRO.
    uso_coll.update_one(
        {"user_id": user_id},
        {"$set": {"pro": True, "pro_expira_em": time.time() + 30*24*60*60}},
        upsert=True
    )
    bot.send_message(message.chat.id, "💎 Pagamento aprovado! Plano PRO ativo por 30 dias 🚀")

# =================================================================
# BLOCO 3 - COMANDOS ADICIONAIS E EXECUÇÃO
# =================================================================

# Os comandos /laudo e /dashboard já estão definidos no Bloco 2.
# Este bloco contém apenas a execução final.

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(2)
    print("Bot iniciado...")
    bot.infinity_polling(timeout=120, long_polling_timeout=60)

    
