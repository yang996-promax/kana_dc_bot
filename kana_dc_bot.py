import discord
from discord.ext import commands
import random
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
import atexit

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

tree = bot.tree

# ===== SQLite 持久化（多用户核心）=====
DB_FILE = "/data/kana_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            score INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            wrong INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id: int):
    """从数据库读取用户数据（多用户持久化）"""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT score, correct, wrong FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row:
        data = {"score": row[0], "correct": row[1], "wrong": row[2]}
    else:
        data = {"score": 0, "correct": 0, "wrong": 0}
        cur.execute("INSERT INTO users (user_id, score, correct, wrong) VALUES (?, 0, 0, 0)", (user_id,))
        conn.commit()
    conn.close()
    return data

def save_user(user_id: int, data: dict):
    """保存用户数据到数据库"""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        UPDATE users SET score = ?, correct = ?, wrong = ? WHERE user_id = ?
    """, (data["score"], data["correct"], data["wrong"], user_id))
    conn.commit()
    conn.close()

# 程序退出时自动保存（Railway 重启保护）
def save_all_on_exit():
    pass  # SQLite 已实时保存，无需额外操作

atexit.register(save_all_on_exit)

# ===== 全局数据 =====
gojuon = [
    ("a", "あ", "ア"), ("i", "い", "イ"), ("u", "う", "ウ"), ("e", "え", "エ"), ("o", "お", "オ"),
    ("ka", "か", "カ"), ("ki", "き", "キ"), ("ku", "く", "ク"), ("ke", "け", "ケ"), ("ko", "こ", "コ"),
    ("sa", "さ", "サ"), ("shi", "し", "シ"), ("su", "す", "ス"), ("se", "せ", "セ"), ("so", "そ", "ソ"),
    ("ta", "た", "タ"), ("chi", "ち", "チ"), ("tsu", "つ", "ツ"), ("te", "て", "テ"), ("to", "と", "ト"),
    ("na", "な", "ナ"), ("ni", "に", "ニ"), ("nu", "ぬ", "ヌ"), ("ne", "ね", "ネ"), ("no", "の", "ノ"),
    ("ha", "は", "ハ"), ("hi", "ひ", "ヒ"), ("fu", "ふ", "フ"), ("he", "へ", "ヘ"), ("ho", "ほ", "ホ"),
    ("ma", "ま", "マ"), ("mi", "み", "ミ"), ("mu", "む", "ム"), ("me", "め", "メ"), ("mo", "も", "モ"),
    ("ya", "や", "ヤ"), ("yu", "ゆ", "ユ"), ("yo", "よ", "ヨ"),
    ("ra", "ら", "ラ"), ("ri", "り", "リ"), ("ru", "る", "ル"), ("re", "れ", "レ"), ("ro", "ろ", "ロ"),
    ("wa", "わ", "ワ"), ("wo", "を", "ヲ"),
    ("n", "ん", "ン"),
] 

user_game = {}      # 仅游戏状态保留在内存
user_locks = {}     # 每个用户独立锁

def get_kana(entry, mode): ...  # 你原来的函数保持不变

async def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

# ===== 超级安全的 defer =====
async def safe_defer(interaction: discord.Interaction, ephemeral: bool = False):
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral)
    except (discord.errors.NotFound, discord.errors.HTTPException) as e:
        err = str(e).lower()
        if any(x in err for x in ["10062", "40060", "unknown interaction", "already been acknowledged"]):
            return
        raise

# ===== QuizView 和 QuizButton（保持不变，仅增加锁）=====
class QuizView(discord.ui.View):
    def __init__(self, correct, options, mode):
        super().__init__(timeout=30)
        self.correct = correct
        self.mode = mode
        for opt in options:
            self.add_item(QuizButton(opt, correct, mode))

class QuizButton(discord.ui.Button):
    def __init__(self, label, correct, mode):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.correct = correct
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        async with await get_user_lock(interaction.user.id):
            user = get_user(interaction.user.id)
            game = user_game.get(interaction.user.id)

            if not game or not game.get("active", False):
                await interaction.response.send_message("⚠️ 游戏已结束，请使用 /kana 重新开始", ephemeral=True)
                return

            if self.label == self.correct:
                user["score"] += 10
                user["correct"] += 1
                result = "✅ 正确！+10 分"
            else:
                user["score"] -= 3
                user["wrong"] += 1
                result = f"❌ 错误！正确答案: {self.correct} (-3 分)"

            # 实时保存到数据库
            save_user(interaction.user.id, user)

            question, correct, options = generate_question(self.mode)
            view = QuizView(correct, options, self.mode)

            await interaction.response.edit_message(
                content=f"{result}\n\n🧠 {question}",
                view=view
            )


# ===== 出题逻辑 =====
def generate_question(mode):
    entry = random.choice(gojuon)
    rom, _, _ = entry
    kana, kana_type = get_kana(entry, mode)

    if random.random() < 0.5:
        question = f"「{rom}」对应的{kana_type}是？"
        correct = kana
        pool = [e for e in gojuon if e != entry]
        options = [correct]
        while len(options) < 4:
            oe = random.choice(pool)
            okana, _ = get_kana(oe, mode)
            if okana not in options:
                options.append(okana)
    else:
        question = f"「{kana}」的罗马字是？"
        correct = rom
        pool = [e for e in gojuon if e[0] != rom]
        options = [correct]
        while len(options) < 4:
            oe = random.choice(pool)
            if oe[0] not in options:
                options.append(oe[0])

    random.shuffle(options)
    return question, correct, options

# ===== 指令 =====
@tree.command(name="kana", description="练习日语50音")
async def kana(interaction: discord.Interaction, mode: int = 3):
    await safe_defer(interaction)

    user_id = interaction.user.id
    async with await get_user_lock(user_id):
        if user_id in user_game and user_game[user_id]["active"]:
            await interaction.followup.send("⚠️ 你已经在游戏中了！先用 /stop 结束当前游戏。", ephemeral=True)
            return
        user_game[user_id] = {"mode": mode, "active": True, "message_id": None}

    question, correct, options = generate_question(mode)
    view = QuizView(correct, options, mode)
    msg = await interaction.followup.send(f"🧠 {question}", view=view)

    async with await get_user_lock(user_id):
        user_game[user_id]["message_id"] = msg.id

@tree.command(name="stop", description="结束当前游戏并结算分数")
async def stop(interaction: discord.Interaction):
    await safe_defer(interaction)

    user_id = interaction.user.id
    user = get_user(user_id)
    async with await get_user_lock(user_id):
        game = user_game.get(user_id)
        if not game or not game.get("active"):
            await interaction.followup.send("你当前没有进行中的游戏。", ephemeral=True)
            return
        game["active"] = False
        message_id = game.get("message_id")
        user_game.pop(user_id, None)

    # 结束旧消息
    if message_id:
        try:
            msg = await interaction.channel.fetch_message(message_id)
            await msg.edit(content="🏁 游戏已结束（本局已结算）", view=None)
        except:
            pass

    await interaction.followup.send(
        f"""🏁 游戏结束！

📊 最终结算：
⭐ Score: {user['score']}
✅ Correct: {user['correct']}
❌ Wrong: {user['wrong']}

👉 输入 /kana 重新开始
""",
        ephemeral=True
    )

@bot.event
async def on_ready():
    init_db()  # 启动时初始化数据库
    await tree.sync()
    print("✅ 机器人已启动 | 多用户持久化已启用 | 数据库文件：kana_data.db")

# ===== 启动 =====
bot.run(os.getenv("DISCORD_TOKEN"))