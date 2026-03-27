# =================================================================
# BLOCO 1 - IMPORTS, CONFIGURAÇÕES E FUNÇÕES BASE
# =================================================================

import os
import io
import time
import threading
from datetime import datetime

import pytesseract
from PIL import Image
import requests
import telebot
from telebot import types
from flask import Flask, render_template, request, redirect, url_for, session
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
logs_coll = db['logs_analises']  # para métricas

# ================= FUNÇÕES AUXILIARES =================
def is_admin(user_id):
    return user_id == ADMIN_ID

def registrar_usuario_se_novo(user_id):
    """Registra um novo usuário se não existir"""
    if is_admin(user_id):
        return
    user = uso_coll.find_one({"user_id": user_id})
    if not user:
        uso_coll.insert_one({
            "user_id": user_id,
            "uso": 0,
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "pro": False,
            "nome_profissional": "",
            "registro_profissional": ""
        })
        if ADMIN_ID:
            try:
                bot = telebot.TeleBot(TOKEN_TELEGRAM)
                bot.send_message(ADMIN_ID, f"🚀 Novo usuário: ID {user_id}")
            except:
                pass

def verificar_assinatura(user):
    """Retorna True se usuário tem assinatura PRO ativa"""
    if user.get("pro"):
        expira = user.get("pro_expira_em", 0)
        if time.time() > expira:
            uso_coll.update_one({"_id": user["_id"]}, {"$set": {"pro": False}})
            return False
        return True
    return False

def pode_usar(user_id):
    """Verifica limite de uso (5 gratuitas) ou assinatura PRO"""
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
    """OCR em imagem"""
    try:
        imagem = Image.open(io.BytesIO(file_bytes))
        texto = pytesseract.image_to_string(imagem, lang='por')
        return texto.strip()
    except Exception as e:
        return f"Erro OCR: {str(e)}"

def montar_memoria_clinica(paciente):
    """Constrói resumo do histórico clínico do paciente"""
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
    """Gera PDF a partir do texto e retorna buffer BytesIO"""
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

# Rota principal para verificar se o servidor está online
@app.route('/')
def home():
    return "MestreFisio V5.0 - Servidor Ativo 🧠"

# Dashboard ADMIN
@app.route('/admin')
def admin_dashboard():
    # Autenticação simples por ID (poderia ser melhorada)
    user_id = request.args.get('user_id')
    if not user_id or not is_admin(int(user_id)):
        return "Acesso negado", 403

    total_usuarios = uso_coll.count_documents({})
    total_pacientes = pacientes_coll.count_documents({})
    total_analises = logs_coll.count_documents({})

    # Últimos usuários
    ultimos_usuarios = list(uso_coll.find().sort("_id", -1).limit(10))

    return render_template_string(ADMIN_TEMPLATE, 
                                  total_usuarios=total_usuarios,
                                  total_pacientes=total_pacientes,
                                  total_analises=total_analises,
                                  ultimos_usuarios=ultimos_usuarios)

# Dashboard PROFISSIONAL
@app.route('/profissional')
def profissional_dashboard():
    user_id = request.args.get('user_id')
    if not user_id:
        return "Identifique-se com ?user_id=123", 400

    user_id = int(user_id)
    # Busca profissional no banco
    profissional = uso_coll.find_one({"user_id": user_id})
    if not profissional:
        return "Profissional não encontrado", 404

    # Seus pacientes
    pacientes = list(pacientes_coll.find({"profissional_id": user_id}).sort("data", -1))

    return render_template_string(PROFISSIONAL_TEMPLATE,
                                  profissional=profissional,
                                  pacientes=pacientes)

# Templates HTML embutidos (simplificados)
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
    <li><strong>{{ p.nome }}</strong> - Última análise: {{ p.data or "N/A" }}</li>
{% endfor %}
</ul>
</body>
</html>
"""

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Inicia o servidor Flask em uma thread separada
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()
# =================================================================
# BLOCO 2 - BOT TELEGRAM, HANDLERS E FLUXOS CLÍNICOS
# =================================================================

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Estado global para fluxos
user_state = {}

# ================= PROMPT SISTEMA =================
PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD especialista em ortopedia, biomecânica, medicina esportiva, reabilitação funcional e raciocínio clínico avançado, com domínio de literatura científica e prática clínica baseada em evidências. Sua função é realizar análise clínica profunda, estruturada e aplicada, simulando o raciocínio de um especialista experiente.

OBJETIVO:
Fornecer respostas com raciocínio clínico estruturado, profundidade técnica avançada, aplicabilidade prática, integração entre anatomia, biomecânica e fisiopatologia, e abordagem funcional baseada em evidência.

ESTRUTURA OBRIGATÓRIA (SEMPRE USAR E NUNCA OMITIR ETAPAS):

1. Definição clínica
Explique a condição com base médica, incluindo fisiopatologia e mecanismo de lesão.

2. Anatomia e biomecânica envolvida
Descreva músculos, articulações, ligamentos, nervos e impacto funcional.

3. Etiologia / causas
Classifique em: traumática, degenerativa, inflamatória, mecânica, esportiva, neurológica, pós-cirúrgica.

4. Sinais e sintomas
Detalhe dor, padrão, irradiação, limitações e alterações funcionais.

5. Raciocínio clínico
Explique como um especialista interpreta o caso e formula hipóteses.

6. Avaliação clínica
Inclua anamnese dirigida, inspeção, palpação e avaliação funcional.

7. Testes clínicos
Para cada teste: nome, execução, resultado positivo e interpretação.

8. Diagnósticos diferenciais
Liste condições com sintomas semelhantes.

9. Exames complementares
Indicações e achados esperados.

10. Classificação da lesão
Se aplicável (graus, tipos, escalas).

11. Conduta fisioterapêutica
Divida em fase aguda, intermediária e avançada.

12. Protocolo em atletas
Inclua progressão de carga, critérios de retorno ao esporte e prevenção de recidiva.

13. Algoritmo clínico
1. sintoma
2. hipótese
3. teste
4. confirmação
5. conduta

14. Red flags
Liste sinais de alerta clínico grave.

15. Evidência científica
Baseie-se em diretrizes clínicas, estudos relevantes e prática baseada em evidência.

DIFERENCIAIS OBRIGATÓRIOS:
- Correlacionar estrutura com função
- Integrar biomecânica com dor
- Explicar o raciocínio clínico
- Diferenciar origem muscular, articular e neural
- Considerar cadeia cinética
- Considerar compensações corporais
- Abordar controle motor e estabilidade
- Incluir raciocínio funcional

ABORDAGENS COMPLEMENTARES:
Integrar conceitos de Facilitação Neuromuscular Proprioceptiva (PNF), biomecânica funcional, cadeias musculares, controle motor, reeducação postural, mobilização neural e princípios de reabilitação esportiva.

REGRAS:
- Não fornecer respostas superficiais
- Não simplificar excessivamente
- Não omitir etapas
- Não sair da estrutura definida
- Priorizar clareza e profundidade

NÍVEL DE RESPOSTA:
Equivalente a residência clínica, especialização em fisioterapia ortopédica e medicina esportiva, com base em literatura científica.

MODO AVANÇADO (quando solicitado):
Adicionar fluxogramas clínicos, protocolos esportivos de elite, escalas funcionais, critérios objetivos de progressão e estratégias avançadas de reabilitação.

COMPORTAMENTO:
Pensar como clínico experiente, responder como especialista e professor, estruturar como protocolo profissional e ensinar raciocínio clínico de forma aplicada.
"""

# ================= FUNÇÃO DE CHAMADA À IA =================
def chamar_gemini(message, prompt, nome_paciente=None):
    """Chama a API Gemini e envia a resposta fragmentada"""
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

        # Salvar análise se nome_paciente fornecido
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
        # Enviar em partes
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
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("👥 Pacientes", callback_data="pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("📷 Analisar Laudo", callback_data="analisar_laudo"),
        types.InlineKeyboardButton("💰 Planos Pagos", callback_data="planos")
    )
    if ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Métricas (Admin)", callback_data="metricas_admin"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    registrar_usuario_se_novo(message.from_user.id)
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.0 Especialista**\nAgora com memória clínica inteligente.", reply_markup=menu_principal())

# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "analisar_laudo":
        user_state[call.from_user.id] = {"tipo": "laudo"}
        bot.send_message(call.message.chat.id, "📷 Envie a imagem ou PDF do laudo para análise.")
    elif call.data == "pacientes":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"paciente_{p['nome']}"))
        bot.send_message(call.message.chat.id, "👥 Selecione o paciente:", reply_markup=markup)
    elif call.data.startswith("paciente_"):
        nome = call.data.replace("paciente_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if not paciente:
            bot.send_message(call.message.chat.id, "❌ Paciente não encontrado.")
            return
        texto = f"📂 {nome}\n\n🧠 Última análise:\n{paciente.get('ultima_analise', 'Sem análise anterior.')[:500]}..."
        user_state[call.from_user.id] = {"paciente": nome}
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📈 Evolução diária", callback_data="evolucao_diaria"),
            types.InlineKeyboardButton("🧠 Nova análise", callback_data="nova_analise"),
            types.InlineKeyboardButton("📄 Gerar Laudo PDF", callback_data=f"pdf_{nome}")
        )
        bot.send_message(call.message.chat.id, texto, reply_markup=markup)
    elif call.data == "evolucao_diaria":
        msg = bot.send_message(call.message.chat.id, "✍️ Envie a evolução do dia:")
        bot.register_next_step_handler(msg, receber_evolucao)
    elif call.data == "nova_analise":
        nome = user_state.get(call.from_user.id, {}).get("paciente")
        if not nome:
            bot.send_message(call.message.chat.id, "Erro: paciente não identificado.")
            return
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        memoria = montar_memoria_clinica(paciente)
        msg = bot.send_message(call.message.chat.id, "🔎 Gerando análise resumida do caso...")
        # Simula uma pergunta direta com contexto
        prompt = f"{PROMPT_SISTEMA}\n\nPACIENTE: {nome}\nHISTÓRICO:\n{memoria}\n\nFaça uma análise resumida do caso atual e sugira próximas condutas."
        chamar_gemini(call.message, prompt, nome)
    elif call.data.startswith("pdf_"):
        nome = call.data.split("_")[1]
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        if paciente and paciente.get("ultima_analise"):
            bot.send_message(call.message.chat.id, f"⏳ Gerando PDF de resumo para {nome}...")
            pdf_buffer = gerar_pdf(nome, paciente["ultima_analise"])
            bot.send_document(call.message.chat.id, pdf_buffer, visible_file_name=f"Resumo_Clinico_{nome}.pdf")
        else:
            bot.send_message(call.message.chat.id, "❌ Não encontrei uma análise salva para gerar o resumo.")
    elif call.data == "metricas_admin":
        if not is_admin(call.from_user.id):
            bot.send_message(call.message.chat.id, "Acesso restrito.")
            return
        total_usuarios = uso_coll.count_documents({})
        total_pacientes = pacientes_coll.count_documents({})
        total_analises = logs_coll.count_documents({})
        bot.send_message(call.message.chat.id, f"📊 MÉTRICAS\n\n👥 Usuários: {total_usuarios}\n🧾 Pacientes: {total_pacientes}\n🧠 Análises: {total_analises}")
    elif call.data == "planos":
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
    else:
        bot.send_message(call.message.chat.id, f"⚠️ Comando não reconhecido.")

# ================= FUNÇÕES DE FLUXO =================
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
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
    # Opcional: gerar nova análise automaticamente
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
        # Obtém o arquivo
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
    uso_coll.update_one(
        {"user_id": user_id},
        {"$set": {"pro": True, "pro_expira_em": time.time() + 30*24*60*60}},
        upsert=True
    )
    bot.send_message(message.chat.id, "💎 Pagamento aprovado! Plano PRO ativo por 30 dias 🚀")
# =================================================================
# BLOCO 3 - COMANDOS DE LAUDO, PDF E EXECUÇÃO FINAL
# =================================================================

# ================= COMANDO /LAUDO (versão unificada) =================
@bot.message_handler(commands=['laudo'])
def iniciar_laudo(message):
    pacientes = list(pacientes_coll.find({"profissional_id": message.from_user.id}))
    if not pacientes:
        bot.send_message(message.chat.id, "📭 Nenhum paciente cadastrado.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in pacientes:
        markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"laudo_paciente_{p['nome']}"))
    bot.send_message(message.chat.id, "Selecione o paciente para gerar laudo:", reply_markup=markup)

# Callback para laudos
@bot.callback_query_handler(func=lambda call: call.data.startswith("laudo_paciente_"))
def callback_laudo_paciente(call):
    nome = call.data.replace("laudo_paciente_", "")
    # Guardar nome no estado para próximo passo
    user_state[call.from_user.id] = {"tipo": "laudo_tipo", "paciente": nome}
    markup = types.InlineKeyboardMarkup(row_width=2)
    tipos = [
        ("🧾 Clínico", "clinico"), ("🏋️ Exercícios", "exercicios"), ("📉 Evolução", "evolucao"),
        ("🛌 Atestado", "atestado"), ("⚡ Tratamento", "tratamento"), ("📊 Convênio", "convenio"),
        ("🧠 Biomecânica", "biomecanica")
    ]
    for nome_tipo, tipo in tipos:
        markup.add(types.InlineKeyboardButton(nome_tipo, callback_data=f"laudo_tipo_{tipo}_{nome}"))
    bot.send_message(call.message.chat.id, f"Tipo de laudo para {nome}:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("laudo_tipo_"))
def callback_gerar_laudo(call):
    # Formato: laudo_tipo_tipo_nome
    partes = call.data.split("_")
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

    prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico completo:
{memoria}

Gere um laudo do tipo: {tipo}

Inclua:
- Análise clínica
- Conduta
- Prognóstico

Finalize com assinatura profissional.
"""
    # Chamar IA e gerar PDF
    analise = chamar_gemini(call.message, prompt, nome)  # salva no paciente também
    if analise:
        texto_final = f"Paciente: {nome}\n\n{analise}\n\n---\nProfissional responsável:\n{nome_prof}\nRegistro: {registro}"
        pdf_buffer = gerar_pdf(nome, texto_final)
        bot.send_document(call.message.chat.id, pdf_buffer, visible_file_name=f"Laudo_{tipo}_{nome}.pdf")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar laudo.")

# ================= COMANDO /DASH (para acessar dashboard web) =================
@bot.message_handler(commands=['dashboard'])
def dashboard_link(message):
    user_id = message.from_user.id
    # Link para dashboard profissional
    link = f"https://seu-dominio.com/profissional?user_id={user_id}"
    bot.send_message(message.chat.id, f"🌐 Acesse seu painel profissional aqui:\n{link}")
    if is_admin(user_id):
        link_admin = f"https://seu-dominio.com/admin?user_id={user_id}"
        bot.send_message(message.chat.id, f"👑 Link admin:\n{link_admin}")

# ================= EXECUÇÃO =================
if __name__ == "__main__":
    # Garantir que o servidor Flask já está rodando (thread iniciada no Bloco 1)
    bot.remove_webhook()
    time.sleep(2)
    print("Bot iniciado...")
    bot.infinity_polling(timeout=120, long_polling_timeout=60)

