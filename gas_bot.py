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

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)

# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR) # Set level for logging
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

def add_location(conn, name, distance):
    cur = conn.cursor()
    cur.execute("INSERT INTO locations (name, distance) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET distance=%s", (name, distance, distance))
    conn.commit()

def get_locations(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, distance FROM locations")
    locations = cur.fetchall()
    return locations

def get_location_distance(conn, name):
  cur = conn.cursor()
  cur.execute("SELECT distance FROM locations WHERE name = %s", (name,))
  location = cur.fetchone()
  return location[0] if location else None

async def get_locations_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
  conn = get_db_connection()
  locations = get_locations(conn)
  conn.close()
  return [
        app_commands.Choice(name=location[0], value=location[0])
        for location in locations if current.lower() in location[0].lower()
    ]

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

@client.tree.command(name="location")
@app_commands.describe(name="Name of location", distance="One way distance to location in miles")
async def location(interaction: discord.Interaction, name: str, distance: float):
    """Adds or updates a common location and its round-trip distance."""
    try:
      conn = get_db_connection()
      round_trip_distance = distance * 2;
      add_location(conn, name, round_trip_distance)
      conn.close()
      await interaction.response.send_message(f"Location '{name}' with a round-trip distance of {round_trip_distance} miles added/updated. Please enter the one way distance, and the bot will calculate the distance for a round trip.")
    except Exception as e:
        logger.error(f"Error in /location command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while adding or updating the location.")

@client.tree.command(name="drove")
@app_commands.describe(
    distance="Distance driven in miles, or a common location name",
    location="Select a location if needed, otherwise enter distance."
)
@app_commands.autocomplete(location=get_locations_autocomplete)
async def drove(interaction: discord.Interaction, distance: str = None, location: str = None):
    """Logs miles driven and calculates cost using the current gas price."""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        current_price = get_current_gas_price(conn)
        if location is not None:
          distance_from_location = get_location_distance(conn, location)
          if distance_from_location is not None:
            cost = calculate_cost(distance_from_location, DEFAULT_MPG, current_price)
            total_owed = user["total_owed"] + cost
            distance_costs = user.get("distance_costs", [])
            distance_costs.append({"distance": distance_from_location, "cost": cost})
            save_user_data(conn, user_id, user_name, total_owed, distance_costs)
            conn.close()
            await interaction.response.send_message(f"Recorded {location} as distance driven. Current cost: ${cost:.2f}")
          else:
             conn.close()
             await interaction.response.send_message(f"The location: {location} was not recognised. Please specify a distance")
        elif distance is not None:
          try:
            distance_float = float(distance)
            cost = calculate_cost(distance_float, DEFAULT_MPG, current_price)
            total_owed = user["total_owed"] + cost
            distance_costs = user.get("distance_costs", [])
            distance_costs.append({"distance": distance_float, "cost": cost})
            save_user_data(conn, user_id, user_name, total_owed, distance_costs)
            conn.close()
            await interaction.response.send_message(f"Recorded {distance} miles driven. Current cost: ${cost:.2f}")
          except ValueError:
             conn.close()
             await interaction.response.send_message(f"The value {distance} is not recognised as a location, or a valid milage. Please specify a valid milage or location.")
        else:
           conn.close()
           await interaction.response.send_message(f"Please specify a distance or location.")

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
*   `/location` **name** **distance**: Adds a common location and its *one-way* distance. The bot automatically doubles it.
    *   **name:** The name of the location.
    *   **distance**: The *one way* distance to that location in miles.
*   `/drove` **distance or location**: Records the miles driven by a user.
    *  **distance**: The distance driven in miles.
   *   **location**: A location previously set by the `/location` command, which will show in a drop down menu.
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
2. **Location:**
    `/location Home 25` (Sets the round-trip distance for home to 50)
3. **Driving:**
     `/drove 50` (Records 50 miles driven)
     `/drove location: Home` (Records a drive to the location "Home")
4. **Payment:**
    `/paid 20` (Records a payment of $20)
    `/paid 20 @OtherUser` (Records a payment of $20 for other user)
4. **Check Balance:**
    `/balance` (Shows your current balance)

**Important Notes:**

*   The bot now uses a single global gas price for all calculations. Use `/filled` to update this price.
*  The `/location` command requires *one way* distances, and the bot will automatically calculate the round trip distance.
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
