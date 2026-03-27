from reportlab.lib.styles import ParagraphStyle
import pytesseract
from PIL import Image
import io
import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')

@app.route('/')
def home():
    return "MestreFisio V5.0 - Memória Clínica Inteligente Ativa 🧠"

def run():
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

# --- ADMIN ---
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)

def is_admin(user_id):
    return user_id == ADMIN_ID

# 🔥 PROTEÇÃO: evita crash se TOKEN vazio
if not TOKEN_TELEGRAM:
    raise ValueError("TOKEN_TELEGRAM não definido nas variáveis de ambiente")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO ---
if not MONGO_URI:
    raise ValueError("MONGO_URI não definido")

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
uso_coll = db['uso_usuarios']

# --- MEMÓRIA CLÍNICA INTELIGENTE ---
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

# --- OCR ---
def extrair_texto_arquivo(file_bytes):
    try:
        imagem = Image.open(io.BytesIO(file_bytes))
        texto = pytesseract.image_to_string(imagem, lang='por')
        return texto.strip()

    except Exception as e:
        return f"Erro OCR: {str(e)}"

# --- CONTROLE DE USO ---
LIMITE_GRATUITO = 5

# 🔥 REGISTRO DE USUÁRIO
def registrar_usuario_se_novo(user_id):

    user = uso_coll.find_one({"user_id": user_id})

    if not user:
        uso_coll.insert_one({
            "user_id": user_id,
            "uso": 0,
            "criado_em": time.strftime("%d/%m/%Y %H:%M")
        })

        if ADMIN_ID:
            try:
                bot.send_message(
                    ADMIN_ID,
                    f"🚀 Novo usuário:\nID: {user_id}"
                )
            except Exception:
                pass

# 🔥 CONTROLE DE USO (VERSÃO ESTÁVEL)
def pode_usar(user_id):
    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})

    # 🔹 usuário novo
    if not user:
        uso_coll.insert_one({"user_id": user_id, "uso": 1})
        return True

    uso_atual = user.get("uso", 0)

    # 🔹 limite atingido
    if uso_atual >= LIMITE_GRATUITO:
        return False

    novo_uso = uso_atual + 1

    uso_coll.update_one(
        {"user_id": user_id},
        {"$set": {"uso": novo_uso}}
    )

    # 🔥 alerta admin
    if novo_uso >= LIMITE_GRATUITO and ADMIN_ID:
        try:
            bot.send_message(
                ADMIN_ID,
                f"⚠️ Usuário atingiu limite:\nID: {user_id}\nUso: {novo_uso}"
            )
        except Exception:
            pass

    return True

# --- PROMPT ---
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

# --- MENU ---
def menu_principal():
    m = types.InlineKeyboardMarkup(row_width=1)

    m.add(
        types.InlineKeyboardButton("➕ Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("👥 Pacientes", callback_data="pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("📷 Analisar Laudo", callback_data="analisar_laudo"),
        types.InlineKeyboardButton("💰 Planos Pagos", callback_data="planos")
    )

    # 🔥 BOTÃO ADMIN (corrigido)
    if ADMIN_ID:
        m.add(
            types.InlineKeyboardButton("📊 Métricas (Admin)", callback_data="metricas_admin")
        )

    return m


@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "🚀 **MestreFisio V5.0 Especialista**\nAgora com memória clínica inteligente.",
        reply_markup=menu_principal()
    )
    
# =========================
# 🧾 COMANDO DE LAUDOS
# =========================

@bot.message_handler(commands=['laudo'])
def iniciar_laudo(message):
    bot.send_message(
        message.chat.id,
        "🧾 Escolha o tipo de laudo:\n\n"
        "🧾 Laudo clínico\n🏋️ Exercícios\n📉 Evolução\n🛌 Atestado\n⚡ Tratamento\n📊 Convênio\n🧠 Biomecânica"
    )


@bot.message_handler(func=lambda message: message.text in [
    "🧾 Laudo clínico",
    "🏋️ Exercícios",
    "📉 Evolução",
    "🛌 Atestado",
    "⚡ Tratamento",
    "📊 Convênio",
    "🧠 Biomecânica"
])
def selecionar_tipo_laudo(message):

    tipo = message.text

    msg = bot.send_message(
        message.chat.id,
        f"✍️ Envie os dados clínicos para gerar:\n{tipo}"
    )

    bot.register_next_step_handler(msg, gerar_laudo, tipo)

# --- ESTADO GLOBAL ---
user_state = {}

# 🔹 CALLBACK CENTRAL
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)

    # 🆕 NOVO PACIENTE
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    # 🧠 DÚVIDA DIRETA IA
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)

    # 📷 ANALISAR LAUDO
    elif call.data == "analisar_laudo":
        user_state[call.from_user.id] = {"tipo": "laudo"}
        bot.send_message(call.message.chat.id, "📷 Envie a imagem ou PDF do laudo para análise.")

    # 👥 MENU PACIENTES
    elif call.data == "pacientes":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
                f"{p['nome']}",
                callback_data=f"paciente_{p['nome']}"
            ))

        bot.send_message(call.message.chat.id, "👥 Selecione o paciente:", reply_markup=markup)

    # 🔹 SUBMENU DO PACIENTE (🔥 CORREÇÃO PRINCIPAL)
    elif call.data.startswith("paciente_"):
        nome = call.data.replace("paciente_", "")

        paciente = pacientes_coll.find_one({
            "profissional_id": call.from_user.id,
            "nome": nome
        })

        if not paciente:
            bot.send_message(call.message.chat.id, "❌ Paciente não encontrado.")
            return

        ultima = paciente.get("ultima_analise", "Sem análise anterior.")

        texto = f"""📂 {nome}

🧠 Última análise:
{ultima[:500]}...
"""

        # 🔥 estado agora NÃO inicia evolução direto
        user_state[call.from_user.id] = {
            "paciente": nome
        }

        # 🔥 SUBMENU CORRETO
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📈 Evolução diária", callback_data="evolucao_diaria"),
            types.InlineKeyboardButton("🧠 Nova análise", callback_data="nova_analise"),
            types.InlineKeyboardButton("📄 Gerar Laudo PDF", callback_data="gerar_pdf")
        )

        bot.send_message(call.message.chat.id, texto, reply_markup=markup)

        # ✍️ EVOLUÇÃO DIÁRIA
    elif call.data == "evolucao_diaria":
        msg = bot.send_message(call.message.chat.id, "✍️ Envie a evolução do dia:")
        bot.register_next_step_handler(msg, receber_evolucao)

# 🧠 ANÁLISE RESUMIDA
    elif call.data == "nova_analise":
    nome_paciente = user_state.get(call.from_user.id, {}).get("paciente")
        if nome_paciente:
            paciente = pacientes_coll.find_one({
            "profissional_id": call.from_user.id,
            "nome": nome_paciente
            }) or {}
            memoria = montar_memoria_clinica(paciente)
        
            prompt = f"""
            {PROMPT_SISTEMA}
        
            Paciente: {nome_paciente}
            Histórico: {memoria}
        
            Gere uma NOVA ANÁLISE RESUMIDA do caso:
            1. RESUMO ATUAL
            2. PROGRESSÃO CLÍNICA
            3. CONDUTAS RECOMENDADAS
            """
            chamar_gemini(call.message, prompt, nome_paciente)
        else:
            bot.send_message(call.message.chat.id, "❌ Paciente não selecionado.")

# 📄 GERAR PDF
    elif call.data.startswith("pdf_"):
        nome = call.data.split("_")[1]

        paciente = pacientes_coll.find_one({
        "profissional_id": call.from_user.id,
        "nome": nome
        })

        if paciente and paciente.get("ultima_analise"):
            bot.send_message(call.message.chat.id, f"⏳ Gerando PDF de resumo para {nome}...")

            pdf_buffer = gerar_pdf(nome, paciente["ultima_analise"])

            bot.send_document(
            call.message.chat.id,
            pdf_buffer,
            visible_file_name=f"Resumo_Clinico_{nome}.pdf"
            )
        else:
            bot.send_message(call.message.chat.id, "❌ Não encontrei uma análise salva para gerar o resumo.")

    # 📂 HISTÓRICO
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            txt = "📂 Pacientes:\n" + "\n".join(
                [f"• {p['nome']} ({p.get('data','')})" for p in pacientes]
            )
            bot.send_message(call.message.chat.id, txt)

    # 📊 ADMIN
    elif call.data == "metricas_admin":

        if not is_admin(call.from_user.id):
            bot.send_message(call.message.chat.id, "Acesso restrito.")
            return

        total_usuarios = uso_coll.count_documents({})
        total_pacientes = pacientes_coll.count_documents({})
        total_analises = sum([u.get("uso", 0) for u in uso_coll.find()])

        bot.send_message(
            call.message.chat.id,
            f"📊 MÉTRICAS\n\n"
            f"👥 Usuários: {total_usuarios}\n"
            f"🧾 Pacientes: {total_pacientes}\n"
            f"🧠 Análises: {total_analises}"
        )

    # 💳 PAGAMENTO
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
            bot.send_message(
                call.message.chat.id,
                f"❌ Erro no pagamento:\n{str(e)}"
            )

    # 🔥 FALLBACK
    else:
        bot.send_message(
            call.message.chat.id,
            f"⚠️ Comando não reconhecido:\n{call.data}"
        )
        
# 🔹 ENTRADA UNIVERSAL (CORAÇÃO DO SISTEMA)
def receber_entrada_usuario(message):
    estado = user_state.get(message.from_user.id)

    if not estado:
        bot.send_message(message.chat.id, "⚠️ Nenhuma ação em andamento.")
        return

    # 📷 LAUDO
    if estado["tipo"] == "laudo":
        processar_laudo(message)

    # 📈 EVOLUÇÃO
    elif estado["tipo"] == "evolucao":
        nome = estado["paciente"]
        salvar_evolucao(message, nome)


# 🔹 PROCESSAR LAUDO


# 🔹 NOVO PACIENTE
def obter_nome_paciente(message):
    nome = message.text.upper().strip()

    user_state[message.from_user.id] = {
        "tipo": "novo_paciente",
        "paciente": nome
    }

    msg = bot.send_message(
        message.chat.id,
        f"✅ Paciente: {nome}\nDescreva o quadro clínico:"
    )
def processar_laudo(message):
    try:
        file_info = bot.get_file(
         message.document.file_id if message.document else message.photo[-1].file_id
        )

        downloaded_file = bot.download_file(file_info.file_path)

        bot.send_message(message.chat.id, "🧠 Extraindo texto do laudo...")

        texto_extraido = extrair_texto_arquivo(downloaded_file)

        if not texto_extraido:
            bot.send_message(message.chat.id, "❌ Não foi possível ler o laudo.")
            return

        prompt = f"""
{PROMPT_SISTEMA}

Analise o seguinte laudo médico:

{texto_extraido}
"""

        chamar_gemini(message, prompt)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro ao processar laudo:\n{str(e)}")


# 🔹 PROCESSAMENTO IA DIRETO
def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\n{message.text}"
    chamar_gemini(message, prompt)

@bot.message_handler(content_types=['photo', 'document'])

def receber_arquivo(message):

    estado = user_state.get(message.from_user.id)

    if not estado:
        bot.send_message(message.chat.id, "⚠️ Nenhuma ação em andamento.")
        return

    if estado["tipo"] == "laudo":

        bot.send_message(message.chat.id, "🔍 Processando laudo...")

        processar_laudo(message)

        user_state.pop(message.from_user.id, None)

# --- FLUXO PACIENTE ---
def obter_nome_paciente_fluxo(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    paciente = pacientes_coll.find_one({"profissional_id": message.from_user.id, "nome": nome}) or {}
    memoria = montar_memoria_clinica(paciente)
    
    # Prompt focado em RESUMO e PRÓXIMAS CONDUTAS
    prompt = f"""
    Atue como Fisioterapeuta PhD. 
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

# =========================
# 📄 SISTEMA DE LAUDOS + PDF
# =========================

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

    
# =========================
# 📄 SISTEMA DE LAUDOS (POR PACIENTE)
# =========================

# --- GERAR PDF ---
def gerar_pdf(nome_paciente, 
texto_analise):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Estilo customizado para o corpo do texto
    style_corpo = ParagraphStyle(
        'Justify',
        parent=styles['Normal'],
        alignment=1, # 1 = Justificado
        fontSize=11,
        leading=14
    )
    
    elementos = []
    # Cabeçalho do Laudo
    elementos.append(Paragraph(f"<b>MESTREFISIO PhD - RESUMO CLÍNICO</b>", styles['Title']))
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(f"<b>PACIENTE:</b> {nome_paciente.upper()}", styles['Normal']))
    elementos.append(Paragraph(f"<b>DATA DA EMISSÃO:</b> {time.strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elementos.append(Spacer(1, 20))
    
    # Conteúdo da Análise
    for linha in texto_analise.split('\n'):
        if linha.strip():
            elementos.append(Paragraph(linha, style_corpo))
            elementos.append(Spacer(1, 8))
            
    doc.build(elementos)
    buffer.seek(0)
    return buffer



# --- COMANDO /laUDO ---
@bot.message_handler(commands=['laudo'])
def iniciar_laudo(message):

    pacientes = list(pacientes_coll.find({"profissional_id": message.from_user.id}))

    if not pacientes:
        bot.send_message(message.chat.id, "📭 Nenhum paciente cadastrado.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)

    for p in pacientes:
        markup.add(types.InlineKeyboardButton(
            p["nome"],
            callback_data=f"laudo_paciente|{p['nome']}"
        ))

    bot.send_message(message.chat.id, "Selecione o paciente:", reply_markup=markup)


# --- CALLBACK LAUDOS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("laudo_"))
def fluxo_laudos(call):

    bot.answer_callback_query(call.id)

    # 🔹 ESCOLHA DO PACIENTE
    if call.data.startswith("laudo_paciente"):
        nome = call.data.split("|")[1]

        markup = types.InlineKeyboardMarkup(row_width=1)

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
            markup.add(types.InlineKeyboardButton(
                nome_tipo,
                callback_data=f"laudo_tipo|{tipo}|{nome}"
            ))

        bot.send_message(call.message.chat.id, f"Tipo de laudo para {nome}:", reply_markup=markup)

    # 🔹 GERAÇÃO DO LAUDO
    elif call.data.startswith("laudo_tipo"):

        _, tipo, nome = call.data.split("|")

        paciente = pacientes_coll.find_one({
            "profissional_id": call.from_user.id,
            "nome": nome
        }) or {}

        memoria = montar_memoria_clinica(paciente)

        user = uso_coll.find_one({"user_id": call.from_user.id}) or {}

        nome_prof = user.get("nome_profissional", "Não informado")
        registro_prof = user.get("registro_profissional", "Não informado")

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

        resposta = chamar_gemini(call.message, prompt)

        if not resposta:
            bot.send_message(call.message.chat.id, "❌ Erro ao gerar laudo.")
            return

        texto_final = f"""
Paciente: {nome}

{resposta}

---

Profissional responsável:
{nome_prof}
Registro: {registro_prof}
"""

        arquivo = gerar_pdf(texto_final, nome, tipo)

        with open(arquivo, "rb") as f:
            bot.send_document(call.message.chat.id, f)
            
@bot.message_handler(content_types=['photo', 'document'])
def receber_arquivo(message):

    estado = user_state.get(message.from_user.id)

    if estado != "aguardando_laudo":
        return

    bot.send_message(message.chat.id, "🔍 Analisando laudo...")

    try:
        resultado = ler_exame(message)

        bot.send_message(
            message.chat.id,
            f"🧠 Resultado da análise:\n\n{resultado}"
        )

    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ Erro ao analisar:\n{str(e)}"
        )

    user_state.pop(message.from_user.id, None)
    
# =========================
# 💰 SISTEMA DE PAGAMENTO PRO + ASSINATURA
# =========================

# --- CONFIRMAÇÃO DO CHECKOUT (OBRIGATÓRIO) ---
@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        print("Erro no pre_checkout:", e)

# --- PAGAMENTO APROVADO ---
@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(message):

    user_id = message.from_user.id

    uso_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "uso": 0,
                "pro": True,
                "pro_expira_em": time.time() + (30 * 24 * 60 * 60)
            }
        },
        upsert=True
    )

    bot.send_message(
        message.chat.id,
        "💎 Pagamento aprovado!\nPlano PRO ativo por 30 dias 🚀"
    )


# --- VERIFICAÇÃO DE ASSINATURA ---
def verificar_assinatura(user):

    if user.get("pro"):
        expira = user.get("pro_expira_em", 0)

        if time.time() > expira:
            uso_coll.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"pro": False}}
            )
            return False

        return True

    return False


# --- CONTROLE DE USO (VERSÃO FINAL UNIFICADA) ---
def pode_usar(user_id):

    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})

    if not user:
        uso_coll.insert_one({"user_id": user_id, "uso": 1})
        return True

    # 🔥 PRO ATIVO
    if verificar_assinatura(user):
        return True

    uso_atual = user.get("uso", 0)

    if uso_atual >= LIMITE_GRATUITO:
        return False

    uso_coll.update_one(
        {"user_id": user_id},
        {"$inc": {"uso": 1}}
    )

    return True


# --- EVOLUÇÃO DIÁRIA + IA (INTEGRADA AO SUBMENU) ---
def salvar_evolucao(message, nome):
    nova_info = message.text
    data_hora = time.strftime('%d/%m/%Y %H:%M')
    
    # Agrega a informação com data e hora no banco
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$push": {"historico_evolucao": {"data": data_hora, "nota": nova_info}}},
        upsert=True
    )
    
    bot.send_message(
        message.chat.id, 
        f"✅ **Evolução diária recebida e agregada às informações anteriores.**\n🕒 Registro: {data_hora}"
    )
    
    # Opcional: Chama a nova análise resumida logo após evoluir
    msg = bot.send_message(message.chat.id, "🔍 Deseja gerar uma **Nova Análise** resumida agora? (Responda com 'Sim' ou use o menu)")
    

    prompt = f"""
    {PROMPT_SISTEMA}

    Paciente: {nome}

    Histórico clínico completo:
    {memoria}

    Nova evolução do dia:
    {nova_info}

    Realize:
    1. Interpretação da evolução
    2. Progressão clínica
    3. Ajuste de conduta
    4. Próximos passos
    5. Prognóstico
    """

    user_state.pop(message.from_user.id, None)

    chamar_gemini(message, prompt, nome)


# --- ADICIONAR INFO CLÍNICA ---
def adicionar_info_clinica(message, nome):

    nova_info = message.text

    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {
            "$push": {
                "registros_clinicos": {
                    "data": time.strftime("%d/%m/%Y"),
                    "info": nova_info
                }
            }
        },
        upsert=True
    )

    paciente = pacientes_coll.find_one({
        "profissional_id": message.from_user.id,
        "nome": nome
    }) or {}

    memoria = montar_memoria_clinica(paciente)

    prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico completo:
{memoria}

Nova informação clínica:
{nova_info}

Realize:
1. Interpretação clínica
2. Impacto no quadro
3. Ajuste de raciocínio
4. Conduta recomendada
5. Prognóstico
"""

    chamar_gemini(message, prompt, nome)


# --- IA ---
def chamar_gemini(message, prompt, nome_paciente=None):

    if not is_admin(message.from_user.id):
        registrar_usuario_se_novo(message.from_user.id)

        if not pode_usar(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 Limite atingido.")
            return None

    aguarde = bot.send_message(message.chat.id, "🧠 Processando...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    try:
        response = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=400
        )

        if response.status_code != 200:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "❌ Erro na API da IA.")
            print(response.text)
            return None

        res_data = response.json()

        try:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
        except Exception:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "⚠️ Erro ao interpretar resposta da IA.")
            print(res_data)
            return None

        # 🔥 salva no paciente
        if nome_paciente:
            pacientes_coll.update_one(
                {
                    "profissional_id": message.from_user.id,
                    "nome": nome_paciente
                },
                {
                    "$set": {
                        "ultima_analise": analise,
                        "data": time.strftime("%d/%m/%Y")
                    }
                },
                upsert=True
            )

        bot.delete_message(message.chat.id, aguarde.message_id)

        # 🔹 quebra mensagens grandes
        for p in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
            bot.send_message(message.chat.id, p)
            time.sleep(1)

        bot.send_message(
            message.chat.id,
            "✅ Finalizado.",
            reply_markup=menu_principal()
        )

        return analise

    except Exception as e:
        print(e)
        bot.send_message(message.chat.id, "❌ Erro na IA.")
        return None


# --- EXECUÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
