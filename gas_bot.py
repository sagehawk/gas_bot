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
from collections import defaultdict
import time
import random

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_NAME = "railway"  # Replace if using a specific database name
TARGET_CHANNEL_ID = 1319440273868062861

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)

# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Set logging level to DEBUG for more info

--- Car Data ---
CARS = [
    {"name": "Black Subaru", "mpg": 20},
    {"name": "Grey Subaru", "mpg": 20},
    {"name": "New Black Subaru", "mpg": 20},
    {"name": "Mercedes", "mpg": 16},
]

# --- Helper Functions ---
def calculate_cost(distance, mpg, price_per_gallon):
    gallons_used = distance / mpg
    return gallons_used * price_per_gallon

def format_activity_log(records): #Keeping this for now
    log_message = ""
    for record in records:
        record_type = record[0]
        user_name = record[1]
        activity_detail = record[2]
        date_obj = datetime.datetime.fromisoformat(record[3])
        formatted_date = date_obj.strftime("%A, %b %d")
        log_message += f"{user_name} {record_type} {activity_detail} on {formatted_date}\n"
    return log_message

def format_balance_message(users_with_miles, interaction):
    message = ""

    # Nickname mapping with specified order
    nickname_mapping = {
        "858864178962235393": "Abbas",  # mrmario
        "513552727096164378": "Sajjad",  # oneofzero
        "758778170421018674": "Jafar",  # agakatulu
        "838206242127085629": "Mosa",  # Yoshisaki
        "393241098002235392": "Ali",  # Agent
    }

    message += "```\n"
    for user_id in nickname_mapping: # iterate through user ids in the specified order
        if user_id in users_with_miles:
            user_data = users_with_miles[user_id]
            nickname = nickname_mapping.get(user_id, user_data.get("name", "Unknown User")) # Get the nickname or default name

            message += f"{nickname}: ${user_data['total_owed']:.2f}\n"
    message += "```\n"

    # Cars low on gas section + cost per mile
    message += "```\n"
    # Get fresh car data from the database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, notes FROM cars")
    car_data = cur.fetchall()
    conn.close()

    for car_name, car_notes in car_data:
        message += f"{car_name}: {car_notes}\n"
    message += "```\n"

    return message

def format_car_usage_message(users_with_miles):
    message = "### User Car Usage\n"
    nickname_mapping = {
        "858864178962235393": "Abbas",  # mrmario
        "513552727096164378": "Sajjad",  # oneofzero
        "758778170421018674": "Jafar",  # agakatulu
        "838206242127085629": "Mosa",  # Yoshisaki
        "393241098002235392": "Ali",  # Agent
    }

    for user_id in nickname_mapping:
        if user_id in users_with_miles:
            user_data = users_with_miles[user_id]
            nickname = nickname_mapping.get(user_id, user_data.get("name", "Unknown User")) # Get the nickname or default name
            message += f"**{nickname}**:\n"
            if user_data['car_usage']:
                for car_usage in user_data['car_usage']:
                    message += f"  > {car_usage['car_name']}: {car_usage['miles']:.2f} miles, ${car_usage['fill_amount']:.2f} in fills\n"
            message += f"  > Total miles: {user_data['total_miles']:.2f}\n"
            message += "\n"
    return message


# --- Database Functions ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def initialize_cars_in_db(conn):
    cur = conn.cursor()
    for car in CARS:
        cur.execute("INSERT INTO cars (name, mpg) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (car["name"], car["mpg"]))
    conn.commit()

def get_car_id_from_name(conn, car_name):
    cur = conn.cursor()
    cur.execute("SELECT id FROM cars WHERE name = %s", (car_name,))
    result = cur.fetchone()  # Store result in a variable
    return result[0] if result else None  # Check the stored result

def get_car_name_from_id(conn, car_id):
    cur = conn.cursor()
    cur.execute("SELECT name FROM cars WHERE id = %s", (car_id,))
    return cur.fetchone()[0] if cur.fetchone() else None

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

def save_user_data(conn, user_id, user_name, total_owed):
  cur = conn.cursor()
  cur.execute("UPDATE users SET name=%s, total_owed=%s WHERE id=%s", (user_name, total_owed, user_id))
  conn.commit()

def get_all_users_with_miles(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_all_users_with_miles_and_car_usage_func()")
    users_data = {}
    for row in cur.fetchall():
      users_data[row[0]] = {
          "name": row[1],
          "total_owed": row[2],
          "total_miles": row[3],
          "car_usage": row[4] if row[4] else []
      }
    return users_data

def add_payment(conn, payer_id, payer_name, amount): # No longer directly used, payment handled in fill
    cur = conn.cursor()
    timestamp_iso = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO payments (timestamp, payer_id, payer_name, amount) VALUES (%s, %s, %s, %s)", (timestamp_iso, payer_id, payer_name, amount))
    conn.commit()

def set_current_gas_price(conn, price_per_gallon): # No longer used, replaced with car cost per mile
    cur = conn.cursor()
    cur.execute("INSERT INTO gas_prices (price) VALUES (%s) ", (price_per_gallon,))
    conn.commit()

def get_current_gas_price(conn): # No longer used, replaced with car cost per mile
    cur = conn.cursor()
    cur.execute("SELECT price FROM gas_prices ORDER BY id DESC LIMIT 1")
    price = cur.fetchone()
    return price[0] if price else 3.30 # Use default from config if no price in DB

def record_drive(conn, user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso):
    cur = conn.cursor()
    cur.execute("CALL record_drive_func(%s, %s, %s, %s, %s, %s, %s)", (user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso))
    conn.commit()


def get_user_drive_history(conn, user_id, limit=5): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_user_drive_history_func(%s, %s)", (user_id, limit))
    return cur.fetchall()

def get_user_fill_history(conn, user_id, limit=5): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_user_fill_history_func(%s, %s)", (user_id, limit))
    return cur.fetchall()

def get_car_drive_history(conn, car_id, limit=5): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_car_drive_history_func(%s, %s)", (car_id, limit))
    return cur.fetchall()

def get_car_fill_history(conn, car_id, limit=5): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_car_fill_history_func(%s, %s)", (car_id, limit))
    return cur.fetchall()

def get_total_miles_driven_by_user(conn, user_id): # Replaced by function in get_all_users_with_miles
    cur = conn.cursor()
    cur.execute("SELECT SUM(distance) FROM drives WHERE user_id = %s", (user_id,))
    total_miles = cur.fetchone()[0]
    return total_miles if total_miles else 0

def get_last_10_activities_for_all_cars(conn): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_last_10_activities_for_all_cars_func()")
    activities_data = {}
    for row in cur.fetchall():
        activities_data[row[0]] = row[1] # car name, activity log string
    return activities_data

def get_last_10_combined_activities_new(conn): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_last_10_combined_activities_func()")
    result = cur.fetchone()
    return result[0] if result else ""

def get_near_empty_cars(conn): # No longer used
    cur = conn.cursor()
    cur.execute("SELECT * FROM get_near_empty_cars()")
    return [row[0] for row in cur.fetchall()]

def get_car_data(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, notes FROM cars")
    car_data = {}
    for row in cur.fetchall():
        car_data[row[0]] = {"notes": row[1]}
    return car_data


# --- Bot Commands ---
class CarDropdown(discord.ui.Select):
    def __init__(self, cars, view_type):
        options = [discord.SelectOption(label=car["name"]) for car in cars]
        super().__init__(placeholder="Choose a car...", options=options)
        self.view_type = view_type

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_car = self.values[0]
        await interaction.response.defer()  # Acknowledge immediately

        try:
            conn = get_db_connection()
            user_id = str(interaction.user.id)
            user_name = interaction.user.name

            if self.view_type == "drove":
                car_name = self.view.selected_car
                car_id = get_car_id_from_name(conn, car_name)
                current_price = get_current_gas_price(conn)  # No longer used
                car_data = next(
                    (car for car in CARS if car["name"] == self.view.selected_car), None
                )
                mpg = car_data["mpg"] if car_data else 20
                cost = calculate_cost(float(self.view.distance), mpg, current_price)  # No longer used

                record_drive(conn, user_id, user_name, car_id, float(self.view.distance), cost, False,
                             datetime.datetime.now().isoformat())

                users_with_miles = get_all_users_with_miles(conn)  # Get fresh user data
                nickname_mapping = {
                    "858864178962235393": "Abbas",  # mrmario
                    "513552727096164378": "Sajjad",  # oneofzero
                    "758778170421018674": "Jafar",  # agakatulu
                    "838206242127085629": "Mosa",  # Yoshisaki
                    "393241098002235392": "Ali",  # Agent
                }
                nickname = nickname_mapping.get(user_id, user_name)  # Get nickname

                public_message = f"**{nickname}** Drove **{car_name}**\n"
                balance_message = format_balance_message(users_with_miles, interaction)
                full_message = public_message + "\n" + balance_message

                # Purging channel
                if interaction.channel.id == TARGET_CHANNEL_ID:
                    await interaction.channel.purge(limit=None)

                # Send the message to the channel
                await interaction.channel.send(full_message)

                await interaction.followup.send("✅ Drive recorded and message sent to channel!", ephemeral=True) #Ephemeral for personal balance

            elif self.view_type == "note":
                car_name = self.view.selected_car
                car_id = get_car_id_from_name(conn, car_name)
                notes = self.view.notes

                cur = conn.cursor()
                with cur:
                    cur.execute("UPDATE cars SET notes = %s WHERE id = %s", (notes, car_id))
                    conn.commit()

                users_with_miles = get_all_users_with_miles(conn)  # Get fresh user data
                nickname_mapping = {
                    "858864178962235393": "Abbas",  # mrmario
                    "513552727096164378": "Sajjad",  # oneofzero
                    "758778170421018674": "Jafar",  # agakatulu
                    "838206242127085629": "Mosa",  # Yoshisaki
                    "393241098002235392": "Ali",  # Agent
                }
                nickname = nickname_mapping.get(user_id, user_name)  # Get nickname

                public_message = f"**{nickname}** added a note for **{car_name}**\n"
                balance_message = format_balance_message(users_with_miles, interaction)
                full_message = public_message + "\n" + balance_message

                # Purging channel
                if interaction.channel.id == TARGET_CHANNEL_ID:
                    await interaction.channel.purge(limit=None)

                # Send the message to the channel
                await interaction.channel.send(full_message)

                await interaction.followup.send("✅ Notes updated and message sent to channel!", ephemeral=True) #Ephemeral for personal balance
            conn.close()

        except Exception as e:
            conn.close()
            logger.error(f"Error in CarDropdown callback: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)

class DroveView(discord.ui.View):
    def __init__(self, distance):
        super().__init__()
        self.add_item(CarDropdown(CARS, "drove"))
        self.selected_car = None
        self.distance = distance

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != int(interaction.message.interaction_metadata.user.id):
            await interaction.response.send_message("This is not your command!", ephemeral=True)
            return False
        return True

class CarDropdownFill(discord.ui.Select):
    def __init__(self, cars):
        options = [discord.SelectOption(label=car["name"]) for car in cars]
        super().__init__(placeholder="Choose a car...", options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_car = self.values[0]
        try:
            await interaction.response.defer()  # Acknowledge the interaction

            conn = get_db_connection()
            user_id = str(interaction.user.id)
            user_name = interaction.user.name
            car_name = self.view.selected_car  # Get car name
            payment_amount = self.view.payment  # Get payment amount
            payer_id = self.view.payer

            logger.debug(f"Fill callback - User ID: {user_id}, User Name: {user_name}, Car Name: {car_name}, Payment: {payment_amount}, Payer ID: {payer_id}") # Log input parameters

            with conn:
              cur = conn.cursor()
              with cur:
                record_fill(
                    conn=conn,
                    user_id=user_id,
                    user_name=user_name,
                    car_name=car_name,
                    gallons=0,  # Dummy Value
                    price_per_gallon=0,  # Dummy Value
                    payment_amount=self.view.payment,
                    timestamp_iso=datetime.datetime.now().isoformat(),
                    payer_id=payer_id
                )

            # Retrieve fresh data
            users_with_miles = get_all_users_with_miles(conn)
            conn.close()

            # Format the balance message
            nickname_mapping = {
                "858864178962235393": "Abbas",  # mrmario
                "513552727096164378": "Sajjad",  # oneofzero
                "758778170421018674": "Jafar",  # agakatulu
                "838206242127085629": "Mosa",  # Yoshisaki
                "393241098002235392": "Ali",  # Agent
            }
            nickname = nickname_mapping.get(user_id, user_name)  # Get nickname

            message = f"{nickname} filled the {car_name} and paid ${payment_amount:.2f}.\n\n"  # Updated Message
            message += format_balance_message(users_with_miles, interaction)

            # Purging channel
            if interaction.channel.id == TARGET_CHANNEL_ID:
                await interaction.channel.purge(limit=None)

            # Send the message to the channel
            await interaction.channel.send(message)

            # Optionally, send a confirmation to the user (ephemeral)
            await interaction.followup.send("✅ Fill recorded and message sent to channel!", ephemeral=True)

        except Exception as e:
            logger.error(f"Fill error: {e}")
            await interaction.followup.send("❌ Failed to record fill", ephemeral=True)


class FillView(discord.ui.View):
    def __init__(self, payment, payer):
        super().__init__()
        self.gallons = 0  # Dummy value
        self.price = 0  # Dummy value
        self.payment = payment
        self.payer = payer
        self.selected_car = None  # Initialize selected_car
        self.add_item(CarDropdownFill(CARS))  # Use the new CarDropdownFill class

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != int(interaction.message.interaction.user.id):
            await interaction.response.send_message("This is not your command!", ephemeral=True)
            return False
        return True

class NoteView(discord.ui.View):
    def __init__(self, notes):
        super().__init__()
        self.add_item(CarDropdown(CARS, "note"))
        self.selected_car = None
        self.notes = notes

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != int(interaction.message.interaction.user.id):
            await interaction.response.send_message("This is not your command!", ephemeral=True)
            return False
        return True

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    conn = get_db_connection()
    initialize_cars_in_db(conn)  # Initialize cars in the database on bot start
    conn.close()
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


@client.tree.command(name="filled")
@app_commands.describe(
    payment="Total payment amount",
    payer="Who paid? (optional)"
)
async def filled(interaction: discord.Interaction,
                payment: float,
                payer: discord.User = None):
    fill_view = FillView(
        payment=payment,
        payer=str(payer.id) if payer else None
    )

    await interaction.response.send_message(
        "Select the car you filled:",
        view=fill_view,
        ephemeral=True
    )


def record_fill(conn, user_id, user_name, car_name, gallons, price_per_gallon,
                payment_amount, timestamp_iso, payer_id=None):
    cur = conn.cursor()
    logger.debug(f"record_fill: user_id={user_id}, user_name={user_name}, car_name={car_name}, gallons={gallons}, price_per_gallon={price_per_gallon}, payment_amount={payment_amount}, payer_id={payer_id}, timestamp_iso={timestamp_iso}") # Log all parameters
    try:
        cur.execute("CALL record_fill_func(%s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, user_name, car_name, float(gallons), float(price_per_gallon),
                     float(payment_amount), timestamp_iso, payer_id))
        conn.commit()
        logger.debug("record_fill_func executed successfully and committed.") # Log success
    except Exception as e:
        logger.error(f"Error in record_fill: {e}")


@client.tree.command(name="drove")
@app_commands.describe(distance="Distance driven in miles")
async def drove(interaction: discord.Interaction, distance: str):
    """Logs miles driven and calculates cost using the current gas price, deletes all messages then provides the balance"""
    view = DroveView(distance)
    await interaction.response.send_message("Which car did you drive?", view=view, ephemeral=True)

@client.tree.command(name="note")
@app_commands.describe(notes="Any notes about the car")
async def note(interaction: discord.Interaction, notes: str):
    """Sets a note for a specific car."""
    view = NoteView(notes)
    await interaction.response.send_message("Which car do you want to add a note to?", view=view, ephemeral=True)


@client.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    """Shows how much each user owes."""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        conn.close()
        await interaction.response.send_message(f"Your current balance: ${user['total_owed']:.2f}", ephemeral=True) #Ephemeral for personal balance
    except Exception as e:
        logger.error(f"Error in /balance command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while retrieving your balance.", ephemeral=True)

@client.tree.command(name="allbalances")
async def allbalances(interaction: discord.Interaction):
    """Shows the balances of all users."""
    await interaction.response.defer()  # Defer response as it might take longer
    try:
        # Purging channel
        if interaction.channel.id == TARGET_CHANNEL_ID:
            await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        conn.close()

        message = format_balance_message(users_with_miles, interaction)

        await interaction.followup.send(message)
    except Exception as e:
        logger.error(f"Error in /allbalances command: {e}", exc_info=True)
        await interaction.followup.send("An error occurred while displaying balances.", ephemeral=True)

@client.tree.command(name="car_usage")
async def car_usage(interaction: discord.Interaction):
    """Displays car usage data."""
    await interaction.response.defer()  # Defer response as it might take longer
    try:
      conn = get_db_connection()
      users_with_miles = get_all_users_with_miles(conn)
      conn.close()

      message = format_car_usage_message(users_with_miles)
      await interaction.followup.send(message)
    except Exception as e:
        logger.error(f"Error in /car_usage command: {e}", exc_info=True)
        await interaction.followup.send("An error occurred while displaying car usage.", ephemeral=True)

@client.tree.command(name="settle")
async def settle(interaction: discord.Interaction):
    """Resets everyone's balance to zero."""
    await interaction.response.defer()  # Defer response
    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)  # Get user list before settling to iterate through
        for user_id, user_data in users_with_miles.items():
            user_name = user_data["name"]
            get_or_create_user(conn, user_id, user_name)  # Ensure user exists
            save_user_data(conn, user_id, user_name, 0)  # Reset balance to 0
        conn.close()

        if interaction.channel.id == TARGET_CHANNEL_ID:
            await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        conn.close()

        message = "Balances have been settled to zero.\n\n"
        message += format_balance_message(users_with_miles, interaction)

        await interaction.followup.send(message)

    except Exception as e:
        logger.error(f"Error in /settle command: {e}", exc_info=True)
        await interaction.followup.send("An error occurred while settling balances.", ephemeral=True)

@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Provides instructions on how to use the Gas Bot."""
    help_message = """
**Gas Bot User Manual**

This bot helps track gas expenses and calculate how much each user owes.

**Commands:**

*   `/filled` **payment_amount** (optional **payer**):  Records gas fill-up, payment, and sets all cars' cost per mile to 0.16. Prompts for car selection.
    *   **payment_amount:** The amount you paid for the fill-up.
    *   **payer:** (Optional) The user who paid for the fill-up.
*   `/drove` **distance**: Records the miles driven by a user. Prompts for car selection.
    *   **distance**: The distance driven in miles.
*   `/note` **notes**: Sets a note for a specific car. Prompts for car selection.
    *   **notes**: Any notes about the car.
*   `/balance`: Shows your current balance (how much you owe or are owed) - *ephemeral, only visible to you*.
*   `/allbalances`: Shows balances of all users, and car notes.
*   `/car_usage`: Shows car usage data, including total miles driven.
*   `/settle`: Resets everyone's balance to zero.
*   `/help`: Displays this help message.

**Example Usage:**

1. **Record Fill-up & Payment:**
    `/filled 35` (Records fill-up with payment $35, and sets all cars' cost per mile to 0.16)
    `/filled 35 payer:@UserName` (Records fill-up with payment $35, sets all cars' cost per mile to 0.16, and attributes the payment to the specified user)
2. **Driving:**
     `/drove 50` (Bot will prompt you to select a car)
3. **Set Car Note:**
    `/note "Tires need air"` (Bot will prompt you to select a car)
4. **Check Balance:**
    `/balance` (Shows your current balance - only visible to you)
    `/allbalances` (Shows all balances and car notes)

**Important Notes:**

*   Use `/filled` to record fill-ups and payments, and set all cars' cost per mile to 0.16.
*   When using `/drove`, select the car you drove.
*   Use `/note` to add or update a note for a car.
*   `/settle` resets all balances to zero.
*   `/balance` is ephemeral and only visible to you for privacy.
*   The `payer` argument in `/filled` is optional. If no payer is specified, the user executing the command is assumed to be the payer.

If you have any questions, feel free to ask!
"""
    await interaction.response.send_message(help_message, ephemeral=True)  # Ephemeral help message


# --- Function to start the bot ---
async def main():
    await client.start(BOT_TOKEN)


# --- Run the Bot ---
if __name__ == "__main__":
    asyncio.run(main())
