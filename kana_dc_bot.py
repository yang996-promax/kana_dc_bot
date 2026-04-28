import discord
from discord.ext import commands
import random
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

tree = bot.tree

# ===== 你的数据  =====
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

user_data = {}

user_game = {}

def get_kana(entry, mode):
    rom, hira, kata = entry
    if mode == 1:
        return hira, "平假名"
    elif mode == 2:
        return kata, "片假名"
    else:
        return (hira, "平假名") if random.random() < 0.5 else (kata, "片假名")

def get_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            "score": 0,
            "correct": 0,
            "wrong": 0
        }
    return user_data[user_id]

# ===== Discord 按钮 UI =====
class QuizView(discord.ui.View):
    def __init__(self, correct, options, mode):
        super().__init__(timeout=30)
        self.correct = correct
        self.mode = mode  # ⭐ 记住模式

        for opt in options:
            self.add_item(QuizButton(opt, correct, mode))


class QuizButton(discord.ui.Button):
    def __init__(self, label, correct, mode):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.correct = correct
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):

        user = get_user(interaction.user.id)
        game = user_game.get(interaction.user.id)

        # ❌ 如果游戏已结束 → 直接禁止操作
        if not game or not game.get("active", False):
            await interaction.response.send_message(
                "⚠️ 游戏已结束，请使用 /kana 重新开始",
                ephemeral=True
            )
            return
        
        if self.label == self.correct:
            user["score"] += 10
            user["correct"] += 1
            result = "✅ 正确！+10 分"
        else:
            user["score"] -= 3
            user["wrong"] += 1
            result = f"❌ 错误！正确答案: {self.correct} (-3 分)"

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

    await interaction.response.defer()  # ⭐ 先回应（避免冲突）

    user_id = interaction.user.id

    if user_id in user_game and user_game[user_id]["active"]:
        await interaction.followup.send(
            "⚠️ 你已经在游戏中了！先用 /stop 结束当前游戏。",
            ephemeral=True
        )
        return

    user_game[user_id] = {
        "mode": mode,
        "active": True,
        "message_id": None
    }

    question, correct, options = generate_question(mode)
    view = QuizView(correct, options, mode)

    msg = await interaction.followup.send(f"🧠 {question}", view=view)

    user_game[user_id]["message_id"] = msg.id

@tree.command(name="stop", description="结束当前游戏并结算分数")
async def stop(interaction: discord.Interaction):

    user_id = interaction.user.id
    user = get_user(user_id)
    game = user_game.get(user_id)

    if not game or not game.get("active"):
        await interaction.response.send_message(
            "你当前没有进行中的游戏。",
            ephemeral=True
        )
        return

    game["active"] = False

    try:
        if game.get("message_id"):
            msg = await interaction.channel.fetch_message(game["message_id"])
            await msg.edit(
                content="🏁 游戏已结束（本局已结算）",
                view=None
            )
    except:
        pass

    user_game.pop(user_id, None)

    # ⭐ 改这里：defer + followup
    await interaction.response.defer()

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
    await tree.sync()
    print("Commands:")
    for cmd in tree.get_commands():
        print(cmd.name)



# ===== 启动 =====
bot.run(os.getenv("DISCORD_TOKEN"))