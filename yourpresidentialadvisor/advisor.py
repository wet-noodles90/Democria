import discord
from discord.ext import commands
import sqlite3
import random
from config import TOKEN

# Set up the bot with proper intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Open the SQLite database with check_same_thread=False for multi-threaded access
conn = sqlite3.connect("democracy.db", check_same_thread=False)
c = conn.cursor()

# Create tables with updated schema
c.execute("""CREATE TABLE IF NOT EXISTS elections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate TEXT,
                candidate_id INTEGER,
                votes INTEGER DEFAULT 0
            )""")

c.execute("""CREATE TABLE IF NOT EXISTS voters (
                user_id INTEGER PRIMARY KEY,
                candidate_id INTEGER
            )""")

# Check and update the elections table schema if necessary
c.execute("PRAGMA table_info(elections)")
columns = [column[1] for column in c.fetchall()]
if 'candidate_id' not in columns:
    c.execute("ALTER TABLE elections ADD COLUMN candidate_id INTEGER")
    conn.commit()

c.execute("""CREATE TABLE IF NOT EXISTS president (
                name TEXT,
                candidate_id INTEGER
            )""")
c.execute("""CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule TEXT
            )""")
c.execute("""CREATE TABLE IF NOT EXISTS tyranny (
                active INTEGER DEFAULT 0
            )""")
c.execute("""CREATE TABLE IF NOT EXISTS polls_status (
                id INTEGER PRIMARY KEY,
                open INTEGER DEFAULT 0
            )""")
c.execute("""CREATE TABLE IF NOT EXISTS debating (
                id INTEGER PRIMARY KEY,
                debating INTEGER DEFAULT 0
            )""")
conn.commit()

# Initialize debating table
c.execute("""INSERT OR IGNORE INTO debating (id, debating) 
            VALUES (1, 0)""")
conn.commit()

# Ensure a row exists in polls_status
c.execute("SELECT COUNT(*) FROM polls_status")
if c.fetchone()[0] == 0:
    c.execute("INSERT INTO polls_status (id, open) VALUES (1, 0)")
    conn.commit()

# Helper functions
def get_current_president():
    c.execute("SELECT name, candidate_id FROM president")
    result = c.fetchone()
    if result:
        return result[0], result[1]
    return None, None

def set_president(name, candidate_id):
    c.execute("DELETE FROM president")
    c.execute("INSERT INTO president (name, candidate_id) VALUES (?, ?)", (name, candidate_id))
    conn.commit()

def is_tyranny():
    c.execute("SELECT active FROM tyranny")
    result = c.fetchone()
    return result[0] if result else 0

def toggle_tyranny(state):
    c.execute("DELETE FROM tyranny")
    c.execute("INSERT INTO tyranny (active) VALUES (?)", (state,))
    conn.commit()

def polls_are_open():
    c.execute("SELECT open FROM polls_status WHERE id = 1")
    result = c.fetchone()
    return result[0] == 1 if result else False

def set_polls(state):
    c.execute("UPDATE polls_status SET open = ? WHERE id = 1", (state,))
    conn.commit()

def is_debating():
    c.execute("SELECT debating FROM debating WHERE id = 1")
    result = c.fetchone()
    return result[0] == 1 if result else False

def set_debates(state):
    c.execute("UPDATE debating SET debating = ? WHERE id = 1", (state,))
    conn.commit()

@bot.event
async def on_ready():
    print(f"{bot.user} is online and ready to govern!")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    
    # Get candidate IDs instead of names
    c.execute("SELECT candidate_id FROM elections")
    candidate_ids = [row[0] for row in c.fetchall()]  # Extract IDs from tuples

    debates = discord.utils.get(bot.get_all_channels(), name='debates')
    supervisor = discord.utils.get(message.guild.roles, name='Supervisor')

    if message.channel == debates:
        # Correct condition: allow if user is candidate AND debates are active
        if (message.author.id not in candidate_ids) or (not is_debating()):
            if supervisor not in message.author.roles:
                await message.delete()
                await message.author.send("Please do not talk in the debates channel!!! If you are a candidate please wait until debating starts.")
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(user):
    channel = user.guild.system_channel
    if channel:
        await channel.send(f"Hello {user.mention} type `!runforpresident` to run and `!candidates` to see all of the candidates!!!")

# Candidate registration (allowed only when polls are closed)
@bot.command()
async def runforpresident(ctx):
    if polls_are_open():
        await ctx.send("🚫 Candidates can only register when polls are closed!")
        return
    candidate = ctx.author.name
    candidate_id = ctx.author.id
    # Check if the user is already registered
    c.execute("SELECT id FROM elections WHERE candidate_id = ?", (candidate_id,))
    if c.fetchone():
        await ctx.send("🚫 You are already registered as a candidate!")
        return
    c.execute("INSERT INTO elections (candidate, candidate_id, votes) VALUES (?, ?, 0)", (candidate, candidate_id))
    conn.commit()
    await ctx.send(f"🚀 {candidate} is now running for President! When polls open, citizens can vote for you using `!vote {candidate}`")

@bot.command()
async def leaverace(ctx):
    # Check if polls are open, stop execution if they are
    if polls_are_open():
        await ctx.send("🚫 Sorry, but you can't leave the race now!")
        return

    candidate_id = ctx.author.id
    # Check if the user is registered as a candidate
    c.execute("SELECT id FROM elections WHERE candidate_id = ?", (candidate_id,))
    row = c.fetchone()
    
    if row is None:
        await ctx.send("🚫 You are not currently registered as a candidate.")
    else:
        # Remove the candidate from the elections table
        c.execute("DELETE FROM elections WHERE candidate_id = ?", (candidate_id,))
        conn.commit()
        await ctx.send(f"✅ {ctx.author.name}, you have successfully withdrawn from the race.")

@bot.command()
async def vote(ctx, *, candidate: str):
    if not polls_are_open():
        await ctx.send("🚫 Voting is not open right now!")
        return

    candidate_id = None
    candidate_name = None

    # Parse user mention
    if candidate.startswith('<@') and candidate.endswith('>'):
        mention = candidate.strip('<@!>')
        try:
            candidate_id = int(mention)
        except ValueError:
            await ctx.send("🚫 Invalid mention format!")
            return
        
        c.execute("SELECT candidate FROM elections WHERE candidate_id = ?", (candidate_id,))
        row = c.fetchone()
        if not row:
            await ctx.send("🚫 The mentioned user is not a candidate!")
            return
        candidate_name = row[0]
    else:
        c.execute("SELECT candidate_id FROM elections WHERE candidate = ?", (candidate,))
        row = c.fetchone()
        if not row:
            await ctx.send("🚫 Candidate not found! Please check the candidate's name.")
            return
        candidate_id = row[0]
        candidate_name = candidate

    user_id = ctx.author.id

    # Check existing vote
    c.execute("SELECT candidate_id FROM voters WHERE user_id = ?", (user_id,))
    existing = c.fetchone()

    if existing:
        previous_candidate_id = existing[0]
        if previous_candidate_id == candidate_id:
            await ctx.send("🚫 You've already voted for this candidate!")
            return
            
        # Remove previous vote
        c.execute("UPDATE elections SET votes = votes - 1 WHERE candidate_id = ?", (previous_candidate_id,))
        c.execute("UPDATE voters SET candidate_id = ? WHERE user_id = ?", (candidate_id, user_id))
        
        # Get previous candidate name
        c.execute("SELECT candidate FROM elections WHERE candidate_id = ?", (previous_candidate_id,))
        prev_name = c.fetchone()[0] if c.fetchone() else "a candidate"
        await ctx.send(f"🗳️ Vote changed from {prev_name} to {candidate_name}!")
    else:
        c.execute("INSERT INTO voters (user_id, candidate_id) VALUES (?, ?)", (user_id, candidate_id))
        await ctx.send(f"🗳️ Vote cast for {candidate_name}!")

    # Add new vote
    c.execute("UPDATE elections SET votes = votes + 1 WHERE candidate_id = ?", (candidate_id,))
    conn.commit()
# Command to list all candidates (named as requested: !canidates)
@bot.command(name="candidates")
async def list_candidates(ctx):
    c.execute("SELECT candidate, votes FROM elections")
    rows = c.fetchall()
    if rows:
        message = "🗳️ **Candidates Running:**\n" + "\n".join([f"{cand} - {votes} vote{'s' if votes != 1 else ''}" for cand, votes in rows])
        await ctx.send(message)
    else:
        await ctx.send("🚫 No candidates are currently running.")

@bot.command()
@commands.has_role("Supervisor")
async def open_debates(ctx):
    await ctx.send("@everyone, debating is finally open!!!!")
    set_debates(1)

@bot.command()
@commands.has_role("Supervisor")
async def close_debates(ctx):
    await ctx.send("@everyone, debating has been closed.")
    set_debates(0)

@bot.command()
async def debating(ctx):
    await ctx.send(f"Debating is {'on' if is_debating() else 'off'}!!!!")

# Command to tally votes and elect a new president once polls are closed.
# Modified close_polls to clear voters
@bot.command()
@commands.has_role("Supervisor")
async def close_polls(ctx):
    set_polls(0)
    c.execute("SELECT candidate, candidate_id, votes FROM elections ORDER BY votes DESC LIMIT 1")
    winner = c.fetchone()
    
    if winner:
        previous_name, previous_id = get_current_president()
        set_president(winner[0], winner[1])
        
        # Clear election data and voters
        c.execute("DELETE FROM elections")
        c.execute("DELETE FROM voters")  # Clear voters
        conn.commit()

        # Role management (unchanged)
        # ... [Keep role management code the same] ...

    await ctx.send(f"🎉 {winner[0]} has been elected!" if winner else "🗳️ No votes cast.")
    
# Command to open polls for voting (only allowed by @Supervisor)
@bot.command()
@commands.has_role("Supervisor")
async def open_polls(ctx):
    set_polls(1)  # Open the polls
    await ctx.send("🗳️ Polls are now open! Citizens can now vote for their preferred candidate.")

@bot.command()
async def president(ctx):
    name, _ = get_current_president()
    await ctx.send(f"🏛️ The current President is: {name if name else 'No one'}")

@bot.command()
async def make_rule(ctx, *, rule):
    current_president, _ = get_current_president()
    if ctx.author.name == current_president or is_tyranny():
        c.execute("INSERT INTO rules (rule) VALUES (?)", (rule,))
        conn.commit()
        await ctx.send(f"📜 New rule enacted: {rule}")
    else:
        await ctx.send("⚠️ Only the President can create rules!")

@bot.command()
async def rules(ctx):
    c.execute("SELECT rule FROM rules")
    rules_list = c.fetchall()
    if rules_list:
        formatted_rules = "\n".join([f"- {r[0]}" for r in rules_list])
        await ctx.send(f"📜 Rules:\n{formatted_rules}")
    else:
        await ctx.send("📜 No rules exist yet.")

@bot.command()
async def tyranny(ctx):
    current_president, _ = get_current_president()
    if ctx.author.name == current_president:
        toggle_tyranny(1)
        await ctx.send("⚠️ The President has declared absolute power! Democracy is suspended!")
    else:
        await ctx.send("⚠️ Only the President can declare tyranny!")

@bot.command()
async def restore_democracy(ctx):
    if is_tyranny():
        if random.randint(1, 10) > 3:  # 70% chance of success
            toggle_tyranny(0)
            set_president(None, None)
            await ctx.send("🎉 The people have revolted! Democracy is restored!")
        else:
            await ctx.send("🚨 The rebellion failed! The tyranny continues!")
    else:
        await ctx.send("⚠️ There is no tyranny to overthrow!")

@bot.command()
async def campaign(ctx):
    await ctx.send(f"📢 {ctx.author.name} is campaigning for President! Support them!")

bot.run(TOKEN)
