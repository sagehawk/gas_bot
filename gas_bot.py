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
TARGET_CHANNEL_ID = 1319440273868062861

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)

# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# --- Car Data ---
CARS = [
    {"name": "Yellow Subaru", "mpg": 20},
    {"name": "Black Subaru", "mpg": 20},
    {"name": "Grey Subaru", "mpg": 20},
    {"name": "Toyota", "mpg": 25}
]

# --- Helper Functions ---
def calculate_cost(distance, mpg, price_per_gallon):
    gallons_used = distance / mpg
    return gallons_used * price_per_gallon

def format_activity_log(records):
    log_message = ""
    for record in records:
        record_type = record[0]
        user_name = record[1]
        activity_detail = record[2]
        date = record[3].strftime('%Y-%m-%d')
        log_message += f"{user_name} {record_type} {activity_detail} on {date}\n"
    return log_message

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
    car_data = cur.fetchone()
    if car_data:
        return car_data[0]
    return None

def get_car_name_from_id(conn, car_id):
    cur = conn.cursor()
    cur.execute("SELECT name FROM cars WHERE id = %s", (car_id,))
    car_data = cur.fetchone()
    if car_data:
        return car_data[0]
    return None

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

def get_all_users(conn):
  cur = conn.cursor()
  cur.execute("SELECT id, name, total_owed FROM users")
  users = {}
  for user in cur.fetchall():
    users[user[0]] = {"name": user[1], "total_owed": user[2]}
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
    return price[0] if price else 3.30 # Use default from config if no price in DB

def record_drive(conn, user_id, user_name, car_id, distance, cost, near_empty):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO drives (timestamp, user_id, user_name, car_id, distance, cost, near_empty) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (datetime.datetime.now().isoformat(), user_id, user_name, car_id, distance, cost, near_empty)
    )
    conn.commit()

def record_fill(conn, user_id, user_name, car_id, amount, price_per_gallon):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO fills (timestamp, user_id, user_name, car_id, amount, price_per_gallon) VALUES (%s, %s, %s, %s, %s, %s)",
        (datetime.datetime.now().isoformat(), user_id, user_name, car_id, amount, price_per_gallon)
    )
    conn.commit()

def get_user_drive_history(conn, user_id, limit=10):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 'drove', user_name, distance || ' miles in ' || (SELECT name FROM cars WHERE id = drives.car_id), timestamp
        FROM drives
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (user_id, limit)
    )
    return cur.fetchall()

def get_user_fill_history(conn, user_id, limit=10):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 'filled', user_name, '$' || amount || ' in ' || (SELECT name FROM cars WHERE id = fills.car_id), timestamp
        FROM fills
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (user_id, limit)
    )
    return cur.fetchall()

def get_car_drive_history(conn, car_id, limit=10):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 'drove', user_name, distance || ' miles', timestamp
        FROM drives
        WHERE car_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (car_id, limit)
    )
    return cur.fetchall()

def get_car_fill_history(conn, car_id, limit=10):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 'filled', user_name, '$' || amount, timestamp
        FROM fills
        WHERE car_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (car_id, limit)
    )
    return cur.fetchall()

def get_total_miles_driven_by_user(conn, user_id):
    cur = conn.cursor()
    cur.execute("SELECT SUM(distance) FROM drives WHERE user_id = %s", (user_id,))
    total_miles = cur.fetchone()[0]
    return total_miles if total_miles else 0

def get_last_10_activities_for_all_cars(conn):
    car_activities = {}
    for car in CARS:
        car_id = get_car_id_from_name(conn, car["name"])
        if car_id:
            drives = get_car_drive_history(conn, car_id, 5) #Get last 5 drives for each car
            fills = get_car_fill_history(conn, car_id, 5) #Get last 5 fills for each car
            activities = sorted(drives + fills, key=lambda x: x[3], reverse=True)[:10] #Combine and sort by timestamp, limit to 10
            car_activities[car["name"]] = format_activity_log(activities)
    return car_activities

def get_last_10_activities_for_user(conn, user_id):
    drives = get_user_drive_history(conn, user_id, 5) # Get last 5 drives
    fills = get_user_fill_history(conn, user_id, 5) # Get last 5 fills
    activities = sorted(drives + fills, key=lambda x: x[3], reverse=True)[:10] # Combine and sort by timestamp, limit to 10
    return format_activity_log(activities)


# --- Bot Commands ---
class CarDropdown(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=car["name"], value=car["name"]) for car in CARS]
        super().__init__(placeholder="Choose a car...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_car = self.values[0]
        await interaction.response.defer() # Acknowledge interaction


class DroveView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(CarDropdown())
        self.selected_car = None
        self.near_empty = False # Initialize near_empty as False

    @discord.ui.button(label="Near Empty", style=discord.ButtonStyle.secondary)
    async def near_empty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.near_empty = not self.near_empty # Toggle near_empty
        if self.near_empty:
            button.style = discord.ButtonStyle.danger # Change style to indicate active
        else:
            button.style = discord.ButtonStyle.secondary # Revert style
        await interaction.response.edit_message(view=self) # Update the view to reflect button change


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    conn = get_db_connection()
    initialize_cars_in_db(conn) # Initialize cars in the database on bot start
    conn.close()
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@client.tree.command(name="filled")
@app_commands.describe(price_per_gallon="Price per gallon", car="Car filled up")
async def filled(interaction: discord.Interaction, price_per_gallon: float, car: str):
    """Updates the current gas price."""
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        car_id = get_car_id_from_name(conn, car)
        if not car_id:
            conn.close()
            await interaction.response.send_message(f"Car '{car}' not found. Please choose from: {', '.join([c['name'] for c in CARS])}")
            return

        record_fill(conn, user_id, user_name, car_id, price_per_gallon * 10 , price_per_gallon) # Assume 10 gallons for simplicity, can be adjusted or made interactive
        set_current_gas_price(conn, price_per_gallon) #Still setting global gas price for now
        conn.close()

        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users = get_all_users(conn)
        car_activities = get_last_10_activities_for_all_cars(conn)
        conn.close()

        message = f"Gas filled recorded for {car} at ${price_per_gallon:.2f} per gallon.\n\nCurrent Balances:\n"
        message += "```\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
               user_name = member.name
            else:
              user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        message += "```\n"
        message += "**Last 10 Activities per Car:**\n"
        for car_name, activities in car_activities.items():
            message += f"**{car_name}**:\n{activities}\n"

        await interaction.response.send_message(message)

    except Exception as e:
        logger.error(f"Error in /filled command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while updating the gas price.")


@client.tree.command(name="drove")
@app_commands.describe(distance="Distance driven in miles")
async def drove(interaction: discord.Interaction, distance: str):
    """Logs miles driven and calculates cost using the current gas price, deletes all messages then provides the balance"""
    view = DroveView()
    await interaction.response.send_message("Which car did you drive and were you near empty?", view=view, ephemeral=True) # Send ephemeral message to get car selection

    try:
        await view.wait() # Wait for the view to be completed (car selection)
        if view.selected_car is None:
            await interaction.followup.send("You did not select a car.", ephemeral=True)
            return

        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.name
        user = get_or_create_user(conn, user_id, user_name)
        current_price = get_current_gas_price(conn)

        car_id = get_car_id_from_name(conn, view.selected_car)
        car_data = next((car for car in CARS if car["name"] == view.selected_car), None) # Find car data

        try:
           distance_float = float(distance)
           mpg = car_data["mpg"] if car_data else 20 # Default MPG if car data not found or as fallback
           cost = calculate_cost(distance_float, mpg, current_price)
           total_owed = user["total_owed"] + cost
           save_user_data(conn, user_id, user_name, total_owed)
           record_drive(conn, user_id, user_name, car_id, distance_float, cost, view.near_empty)
           conn.close()
           last_drive_message =  f"**{user_name}**: Recorded {distance} miles driven in {view.selected_car}. Current cost: ${cost:.2f}. {'(Near Empty)' if view.near_empty else ''}\n\n"
        except ValueError:
            conn.close()
            await interaction.followup.send(f"The value {distance} is not a valid number. Please specify a valid mileage.", ephemeral=True)
            return

        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users = get_all_users(conn)
        car_activities = get_last_10_activities_for_all_cars(conn)
        conn.close()

        message = f"{last_drive_message}Current Balances:\n"
        message += "```\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
               user_name = member.name
            else:
              user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        message += "```\n"
        message += "**Last 10 Activities per Car:**\n"
        for car_name, activities in car_activities.items():
            message += f"**{car_name}**:\n{activities}\n"

        await interaction.followup.send(message) # Send the balance message as followup

    except Exception as e:
        logger.error(f"Error in /drove command: {e}", exc_info=True)
        await interaction.followup.send("An error occurred while recording the distance driven.", ephemeral=True) # Send error as followup


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
    try:
        conn = get_db_connection()
        users = get_all_users(conn)
        car_activities = get_last_10_activities_for_all_cars(conn)
        conn.close()
        message = "Current Balances:\n"
        message += "```\n"
        near_empty_cars_list = []
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
                user_name = member.name
            else:
                user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"

            cur = conn.cursor() #Need a new cursor here, or reuse and reconnect. Let's reconnect for simplicity in this example.
            conn_inner = get_db_connection()
            cur_inner = conn_inner.cursor()
            cur_inner.execute("SELECT car_id FROM drives WHERE user_id = %s AND near_empty = TRUE ORDER BY timestamp DESC LIMIT 1", (user_id,))
            last_near_empty_drive = cur_inner.fetchone()
            conn_inner.close()
            if last_near_empty_drive:
                car_name = get_car_name_from_id(conn, last_near_empty_drive[0])
                near_empty_cars_list.append(car_name)

        message += "```\n"
        if near_empty_cars_list:
            message += "\n**Cars marked as near empty recently:** " + ", ".join(near_empty_cars_list) + "\n"
        message += "**Last 10 Activities per Car:**\n"
        for car_name, activities in car_activities.items():
            message += f"**{car_name}**:\n{activities}\n"

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
        get_or_create_user(conn, user_id, user_name) # Ensure user exists
        save_user_data(conn, user_id, user_name, 0)
        conn.close()

        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users = get_all_users(conn)
        car_activities = get_last_10_activities_for_all_cars(conn)
        conn.close()

        message = "Balances have been settled to zero.\n\nCurrent Balances:\n"
        message += "```\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
               user_name = member.name
            else:
              user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        message += "```\n"
        message += "**Last 10 Activities per Car:**\n"
        for car_name, activities in car_activities.items():
            message += f"**{car_name}**:\n{activities}\n"
        await interaction.response.send_message(message)

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

        user_data = get_or_create_user(conn, payer_id, user_name)
        total_owed = user_data["total_owed"] - amount
        save_user_data(conn, payer_id, user_name, total_owed)
        add_payment(conn, payer_id, user_name, amount)
        conn.close()

        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users = get_all_users(conn)
        car_activities = get_last_10_activities_for_all_cars(conn)
        conn.close()

        message = f"Payment of ${amount:.2f} recorded for {user_name}. New balance is ${total_owed:.2f}\n\nCurrent Balances:\n"
        message += "```\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
               user_name = member.name
            else:
              user_name = user_data.get("name", "Unknown User")
            message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
        message += "```\n"
        message += "**Last 10 Activities per Car:**\n"
        for car_name, activities in car_activities.items():
            message += f"**{car_name}**:\n{activities}\n"
        await interaction.response.send_message(message)


    except Exception as e:
       logger.error(f"Error in /paid command: {e}", exc_info=True)
       await interaction.response.send_message("An error occurred while recording the payment.")

@client.tree.command(name="car_usage")
async def car_usage(interaction: discord.Interaction):
    """Shows total miles driven by each user and their last 10 activities."""
    try:
        conn = get_db_connection()
        users = get_all_users(conn)
        message = "Car Usage Statistics:\n\n"
        for user_id, user_data in users.items():
            member = interaction.guild.get_member(int(user_id))
            if member:
                user_name = member.name
            else:
                user_name = user_data.get("name", "Unknown User")
            total_miles = get_total_miles_driven_by_user(conn, user_id)
            message += f"**{user_name}**: Total Miles Driven: {total_miles:.2f} miles\n"
            last_10_activities = get_last_10_activities_for_user(conn, user_id)
            if last_10_activities:
                message += "  **Last 10 Activities:**\n" + last_10_activities
            else:
                message += "  No recent activity recorded.\n"
            message += "\n"
        conn.close()
        await interaction.response.send_message(message)
    except Exception as e:
        logger.error(f"Error in /car_usage command: {e}", exc_info=True)
        await interaction.response.send_message("An error occurred while fetching car usage data.")


@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Provides instructions on how to use the Gas Bot."""
    help_message = """
**Gas Bot User Manual**

This bot helps track gas expenses and calculate how much each user owes.

**Commands:**

*   `/filled` **price_per_gallon** **car**:  Updates the current gas price and records a fill-up.
    *   **price_per_gallon:** The price per gallon.
    *   **car:** The car that was filled (Yellow Subaru, Black Subaru, Grey Subaru, Toyota).
*   `/drove` **distance**: Records the miles driven by a user, prompts for car selection and near empty status.
    *   **distance**: The distance driven in miles.
*   `/balance`: Shows your current balance (how much you owe or are owed) - *ephemeral, only visible to you*.
*   `/allbalances`: Shows the balances of all users and last activities for each car.
*   `/paid` **amount** [user]: Records a payment you made towards your balance.
    *   **amount:** The amount paid.
    *   **user:** (Optional) If specified, sets the amount for another user.
*   `/settle`: Resets everyone's balance to zero.
*   `/car_usage`: Shows total miles driven by each user and their last 10 activities.
*   `/help`: Displays this help message.

**Example Usage:**

1. **Update Gas Price & Fill-up:**
    `/filled 3.50 Yellow Subaru` (Updates the gas price and records a fill-up for Yellow Subaru)
2. **Driving:**
     `/drove 50` (Bot will prompt you to select a car and near empty status)
4. **Payment:**
    `/paid 20` (Records a payment of $20 for yourself)
    `/paid 20 @OtherUser` (Records a payment of $20 for OtherUser)
4. **Check Balance:**
    `/balance` (Shows your current balance - only visible to you)
    `/allbalances` (Shows all balances and car activities)
5. **Car Usage:**
    `/car_usage` (Shows total miles driven by each user)

**Important Notes:**

*   Use `/filled` to update the gas price and record fill-ups, specifying the car.
*   When using `/drove`, select the car you drove and indicate if it was near empty.
*   `/settle` resets all balances to zero.
*   `/car_usage` provides insights into driving activity.
*   `/balance` is ephemeral and only visible to you for privacy.

If you have any questions, feel free to ask!
"""
    await interaction.response.send_message(help_message, ephemeral=True) #Ephemeral help message

# --- Function to start the bot ---
async def main():
    await client.start(BOT_TOKEN)

# --- Run the Bot ---
if __name__ == "__main__":
    asyncio.run(main())
