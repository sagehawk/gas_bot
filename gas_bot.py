import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import psycopg2
from psycopg2 import sql
import logging

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_NAME = "railway" # Replace if using a specific database name
TARGET_CHANNEL_ID = 1320966290642571314

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)

# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# --- MPG Data ---
DEFAULT_MPG = 20  # Default MPG for all calculations

# --- Gas Price Data ---
CURRENT_GAS_PRICE = 3.30  # Default gas price

# --- Database Functions ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def get_or_create_user(conn, user_id, user_name):
  cur = conn.cursor()
  cur.execute("SELECT name, total_owed FROM users WHERE id = %s", (user_id,))
  user = cur.fetchone()
  if user is None:
    cur.execute("INSERT INTO users (id, name, total_owed) VALUES (%s, %s, %s)", (user_id, user_name, 0))
    conn.commit()
    return {"name": user_name, "total_owed": 0}
  else:
    return {"name": user[0], "total_owed": user[1]}

def save_user_data(conn, user_id, user_name, total_owed, distance_costs):
  cur = conn.cursor()
  cur.execute("UPDATE users SET name=%s, total_owed=%s WHERE id=%s", (user_name, total_owed, user_id))
  cur.execute("DELETE FROM distance_costs WHERE user_id = %s", (user_id,))
  for distance_cost in distance_costs:
    cur.execute("INSERT INTO distance_costs (user_id, distance, cost) VALUES (%s, %s, %s)", (user_id, distance_cost["distance"], distance_cost["cost"]))
  conn.commit()

def get_all_users(conn):
  cur = conn.cursor()
  cur.execute("SELECT id, name, total_owed FROM users")
  users = {}
  for user in cur.fetchall():
    cur.execute("SELECT distance, cost FROM distance_costs WHERE user_id = %s", (user[0],))
    distance_costs = [{"distance": row[0], "cost": row[1]} for row in cur.fetchall()]
    users[user[0]] = {"name": user[1], "total_owed": user[2], "distance_costs": distance_costs}
  return users

def add_payment(conn, payer_id, payer_name, amount):
    cur = conn.cursor()
    cur.execute("INSERT INTO payments (timestamp, payer_id, payer_name, amount) VALUES (%s, %s, %s, %s)", (datetime.datetime.now().isoformat(), payer_id, payer_name, amount))
    conn.commit()

def set_current_gas_price(conn, price_per_gallon):
    cur = conn.cursor()
    cur.execute("INSERT INTO gas_prices (price) VALUES (%s) ", (price_per_gallon,))
    conn.commit()

def get_current_gas_price(conn):
    cur = conn.cursor()
    cur.execute("SELECT price FROM gas_prices ORDER BY id DESC LIMIT 1")
    price = cur.fetchone()
    return price[0] if price else CURRENT_GAS_PRICE


# --- Helper Functions ---
def calculate_cost(distance, mpg, price_per_gallon):
    gallons_used = distance / mpg
    return gallons_used * price_per_gallon

# --- Bot Commands ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@client.tree.command(name="filled")
@app_commands.describe(price_per_gallon="Price per gallon")
async def filled(interaction: discord.Interaction, price_per_gallon: float):
    """Updates the current gas price."""
    try:
        conn = get_db_connection()
        set_current_gas_price(conn, price_per_gallon)
        conn.close()
        await interaction.response.send_message(f"Current gas price updated to ${price_per_gallon:.2f}")
    except Exception as e:
        logger.error(f"Error in /filled command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while updating the gas price.")

@client.tree.command(name="drove")
@app_commands.describe(distance="Distance driven in miles")
async def drove(interaction: discord.Interaction, distance: str):
    """Logs miles driven and calculates cost using the current gas price, deletes all messages then provides the balance"""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        current_price = get_current_gas_price(conn)
        try:
           distance_float = float(distance)
           cost = calculate_cost(distance_float, DEFAULT_MPG, current_price)
           total_owed = user["total_owed"] + cost
           distance_costs = user.get("distance_costs", [])
           distance_costs.append({"distance": distance_float, "cost": cost})
           save_user_data(conn, user_id, user_name, total_owed, distance_costs)
           conn.close()
           last_drive_message =  f"{user_name}: Recorded {distance} miles driven. Current cost: ${cost:.2f}\n"
        except ValueError:
            conn.close()
            await interaction.response.send_message(f"The value {distance} is not a valid number. Please specify a valid milage.")
            return
        
        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)
        
        conn = get_db_connection()
        users = get_all_users(conn)
        conn.close()
        message = f"{last_drive_message}Current Balances:\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
               user_name = member.name
            else:
              user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        
        await interaction.response.send_message(message)
        
    except Exception as e:
        logger.error(f"Error in /drove command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while recording the distance driven.")


@client.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    """Shows how much each user owes."""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        conn.close()
        await interaction.response.send_message(f"Your current balance: ${user['total_owed']:.2f}")
    except Exception as e:
        logger.error(f"Error in /balance command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while retrieving your balance.")

@client.tree.command(name="allbalances")
async def allbalances(interaction: discord.Interaction):
    """Shows the balances of all users."""
    try:
        conn = get_db_connection()
        users = get_all_users(conn)
        conn.close()
        message = "Current Balances:\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
                user_name = member.name
            else:
                user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        await interaction.response.send_message(message)
    except Exception as e:
        logger.error(f"Error in /allbalances command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while displaying balances.")

@client.tree.command(name="settle")
async def settle(interaction: discord.Interaction):
    """Resets your balance to zero."""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        save_user_data(conn, user_id, user_name, 0, [])
        conn.close()
        await interaction.response.send_message("Your balance has been settled.")
    except Exception as e:
        logger.error(f"Error in /settle command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while settling your balance.")

@client.tree.command(name="paid")
@app_commands.describe(amount="Amount paid", user="User to pay for, leave blank for yourself")
async def paid(interaction: discord.Interaction, amount: float, user: discord.Member = None):
    """Records a payment made by a user, or for a user."""
    try:
        conn = get_db_connection()
        if user is None:
           payer_id = str(interaction.user.id)
           user_name = interaction.user.name
        else:
           payer_id = str(user.id)
           user_name = user.name

        user = get_or_create_user(conn, payer_id, user_name)
        total_owed = user["total_owed"] - amount
        save_user_data(conn, payer_id, user_name, total_owed, user.get("distance_costs", []))
        add_payment(conn, payer_id, user_name, amount)
        conn.close()
        await interaction.response.send_message(f"Payment of ${amount:.2f} recorded for {user_name}. New balance is ${total_owed:.2f}")
    except Exception as e:
       logger.error(f"Error in /paid command: {e}", exc_info=True)
       await interaction.response.send_message("An error occurred while recording the payment.")

@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Provides instructions on how to use the Gas Bot."""
    help_message = """
**Gas Bot User Manual**

This bot helps track gas expenses and calculate how much each user owes.

**Commands:**

*   `/filled` **price_per_gallon**:  Updates the current gas price.
    *   **price_per_gallon:** The new price per gallon.
*   `/drove` **distance**: Records the miles driven by a user.
    *   **distance**: The distance driven in miles.
*   `/balance`: Shows your current balance (how much you owe or are owed).
*   `/allbalances`: Shows the balances of all users.
*   `/paid` **amount**: Records a payment you made towards your balance.
    *   **amount:** The amount paid.
    *   **user:** If specified, sets the amount for another user.
*   `/settle`: Resets your balance to zero (use this after you've paid in full).
*   `/help`: Displays this help message.

**Example Usage:**

1. **Update Gas Price:**
    `/filled 3.50` (Updates the gas price to $3.50/gallon)
2. **Driving:**
     `/drove 50` (Records 50 miles driven)
4. **Payment:**
    `/paid 20` (Records a payment of $20)
    `/paid 20 @OtherUser` (Records a payment of $20 for other user)
4. **Check Balance:**
    `/balance` (Shows your current balance)

**Important Notes:**

*   The bot now uses a single global gas price for all calculations. Use `/filled` to update this price.
*   `/settle` should only be used after you've paid your balance in full outside of the bot (e.g., via Zelle or another method).
*   Negative balances are allowed and indicate that a user has pre-paid.

If you have any questions, feel free to ask!
"""
    await interaction.response.send_message(help_message)

# --- Function to start the bot ---
async def main():
    await client.start(BOT_TOKEN)

# --- Run the Bot ---
if __name__ == "__main__":
    asyncio.run(main())
