import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.0 - Memória Clínica Inteligente Ativa 🧠"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

# --- ADMIN ---
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

def is_admin(user_id):
    return user_id == ADMIN_ID

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO ---
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
        for r in paciente["registros_clinicos"][-5:]:
            memoria += f"- ({r['data']}) {r['info']}\n"

    return memoria.strip()

# --- CONTROLE DE USO ---
LIMITE_GRATUITO = 5

# 🔥 NOVO: registrar usuário + alerta admin
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
            except:
                pass

def pode_usar(user_id):
    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})

    if not user:
        uso_coll.insert_one({"user_id": user_id, "uso": 1})
        return True

    if user["uso"] >= LIMITE_GRATUITO:
        return False

    novo_uso = user["uso"] + 1

    uso_coll.update_one(
        {"user_id": user_id},
        {"$set": {"uso": novo_uso}}
    )

    # 🔥 ALERTA ADMIN
    if novo_uso >= LIMITE_GRATUITO:
        try:
            bot.send_message(
                ADMIN_ID,
                f"⚠️ Usuário atingiu limite:\nID: {user_id}\nUso: {novo_uso}"
            )
        except:
            pass

    return True

# --- PROMPT ---
PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios (Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências). 
Use linguagem científica de alto nível e formatação Markdown clara.
"""

# --- MENU ---

def menu_principal():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("➕ Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("👥 Pacientes", callback_data="pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("📷 Analisar Laudo", callback_data="ler_exame"),
        types.InlineKeyboardButton("💰 Planos Pagos", callback_data="planos")
    )
    return m
    
    # 🔥 BOTÃO ADMIN
    markup.add(
        types.InlineKeyboardButton("📊 Métricas (Admin)", callback_data="metricas_admin")
    )

    return markup

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
    menu_laudos(message.chat.id)


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

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)

    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            txt = "📂 **Seus Pacientes:**\n" + "\n".join([f"• {p['nome']} ({p['data']})" for p in pacientes])
            bot.send_message(call.message.chat.id, txt)

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

    elif call.data == "atualizar_prontuario":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
                f"{p['nome']}",
                callback_data=f"editar_{p['nome']}"
            ))

        bot.send_message(call.message.chat.id, "📝 Selecione o paciente:", reply_markup=markup)

    # 🔹 EDITAR PACIENTE (lista)
    elif call.data == "editar_paciente":

        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
            f"{p['nome']}",
            callback_data=f"editar_{p['nome']}"
        ))

        bot.send_message(call.message.chat.id, "📝 Selecione o paciente:", reply_markup=markup)


# 🔹 ABRIR PACIENTE
    elif call.data.startswith("editar_"):
        nome = call.data.replace("editar_", "")

        paciente = pacientes_coll.find_one({
        "profissional_id": call.from_user.id,
        "nome": nome
        })

        if not paciente:
            bot.send_message(call.message.chat.id, "❌ Paciente não encontrado.")
            return

        resumo = paciente.get("evolucao", "Sem evolução registrada ainda.")
        ultima = paciente.get("ultima_analise", "Sem análise prévia.")

        texto = f"""📂 {nome}

    🧠 Última análise:
    {ultima[:500]}...

    📈 Evolução:
    {resumo}
    """

    msg = bot.send_message(
        call.message.chat.id,
        texto + "\n\n✍️ Envie nova evolução:"
    )

    bot.register_next_step_handler(msg, salvar_evolucao, nome)


# 🔹 ADICIONAR INFO CLÍNICA (lista)
    elif call.data == "add_info":

        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
            f"{p['nome']}",
            callback_data=f"addinfo_{p['nome']}"
        ))

        bot.send_message(call.message.chat.id, "➕ Selecione o paciente:", reply_markup=markup)


# 🔹 INSERIR INFO CLÍNICA
    elif call.data.startswith("addinfo_"):
        nome = call.data.replace("addinfo_", "")

        msg = bot.send_message(
        call.message.chat.id,
        f"🧠 Envie a nova informação clínica para {nome}:"
        )

        bot.register_next_step_handler(msg, adicionar_info_clinica, nome)


# 🔹 LISTAR PACIENTES
    elif call.data == "pacientes":
        listar_pacientes(call.message)


# 🔹 ANALISAR LAUDO
    elif call.data == "analisar_laudo":
        bot.send_message(
        call.message.chat.id,
        "📷 Envie a imagem ou PDF do laudo para análise."
        )


# 🔹 PLANOS / PAGAMENTO
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


# 🔥 FALLBACK (ANTI-BUG)
    else:
        bot.send_message(
            call.message.chat.id,
            f"⚠️ Comando não reconhecido:\n{call.data}"
    )


# --- FLUXO PACIENTE ---
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):

    paciente = pacientes_coll.find_one({
        "profissional_id": message.from_user.id,
        "nome": nome
    }) or {}

    memoria = montar_memoria_clinica(paciente)

    prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico:
{memoria}

Nova informação:
{message.text}

Atualize o raciocínio considerando toda evolução.
"""

    chamar_gemini(message, prompt, nome)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\n{message.text}"
    chamar_gemini(message, prompt)

# =========================
# 📄 SISTEMA DE LAUDOS + PDF
# =========================

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

    
# =========================
# 📄 SISTEMA DE LAUDOS (POR PACIENTE)
# =========================

# --- GERAR PDF ---
def gerar_pdf(texto, nome_paciente="Paciente", tipo="Laudo"):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4

    nome_arquivo = f"{tipo}_{nome_paciente}.pdf".replace(" ", "_")

    doc = SimpleDocTemplate(nome_arquivo, pagesize=A4)
    styles = getSampleStyleSheet()
    conteudo = []

    # 🔥 TÍTULO
    conteudo.append(Paragraph(f"<b>{tipo.upper()}</b>", styles["Title"]))
    conteudo.append(Spacer(1, 20))

    # 🔥 TEXTO FORMATADO
    for linha in texto.split("\n"):
        if linha.strip() == "":
            continue

        # Destaque para títulos
        if linha.startswith("#") or linha.endswith(":"):
            conteudo.append(Paragraph(f"<b>{linha}</b>", styles["Heading3"]))
        else:
            conteudo.append(Paragraph(linha, styles["Normal"]))

        conteudo.append(Spacer(1, 10))

    doc.build(conteudo)
    return nome_arquivo


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

    # 🔥 libera PRO por 30 dias
    uso_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "uso": 0,
                "pro": True,
                "pro_expira_em": time.time() + (30 * 24 * 60 * 60)  # 30 dias
            }
        },
        upsert=True
    )

    bot.send_message(
        message.chat.id,
        "💎 Pagamento aprovado!\nPlano PRO ativo por 30 dias 🚀"
    )


# --- VERIFICAÇÃO DE EXPIRAÇÃO ---
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


# --- RENOVAÇÃO AUTOMÁTICA (simples) ---
def renovar_plano(user_id):

    uso_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "pro": True,
                "pro_expira_em": time.time() + (30 * 24 * 60 * 60)
            }
        }
    )


# --- ALTERAÇÃO NA FUNÇÃO DE USO ---
def pode_usar(user_id):

    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})

    if not user:
        uso_coll.insert_one({"user_id": user_id, "uso": 1})
        return True

    # 🔥 VERIFICA ASSINATURA
    if verificar_assinatura(user):
        return True

    if user["uso"] >= LIMITE_GRATUITO:
        return False

    uso_coll.update_one(
        {"user_id": user_id},
        {"$inc": {"uso": 1}}
    )

    return True
# --- ATUALIZAÇÃO DE PRONTUÁRIO COM IA ---
def salvar_evolucao(message, nome):

    nova_info = message.text

    paciente = pacientes_coll.find_one({
        "profissional_id": message.from_user.id,
        "nome": nome
    }) or {}

    evolucao_antiga = paciente.get("evolucao", "")

    nova_evolucao = evolucao_antiga + f"\n\n[{time.strftime('%d/%m/%Y')}]\n{nova_info}"

    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$set": {"evolucao": nova_evolucao}},
        upsert=True
    )

    memoria = montar_memoria_clinica({
        **paciente,
        "evolucao": nova_evolucao
    })

    prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico completo:
{memoria}

Nova evolução:
{nova_info}

Realize:
1. Análise pós evolução
2. Interpretação da progressão clínica
3. Ajustes no raciocínio fisioterapêutico
4. Próximas condutas recomendadas
5. Prognóstico
"""

    chamar_gemini(message, prompt, nome)


# --- ADICIONAR INFORMAÇÃO CLÍNICA COM IA ---
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
1. Interpretação clínica da nova informação
2. Impacto no quadro geral
3. Ajuste do raciocínio clínico
4. Conduta fisioterapêutica recomendada
5. Prognóstico atualizado
"""

    chamar_gemini(message, prompt, nome)

# --- IA ---
def chamar_gemini(message, prompt, nome_paciente=None):

    if not is_admin(message.from_user.id):
        registrar_usuario_se_novo(message.from_user.id)

        if not pode_usar(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 Limite atingido.")
            return

    aguarde = bot.send_message(message.chat.id, "🧠 Processando...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    try:
        response = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=400
        )

        res_data = response.json()

        try:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
        except:
            bot.delete_message(message.chat.id, aguarde.message_id)
            bot.send_message(message.chat.id, "⚠️ Erro ao interpretar resposta da IA.")
            print(res_data)
            return

        # ✅ ESTE BLOCO PRECISA ESTAR DENTRO DO TRY
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

# --- EXECUÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
