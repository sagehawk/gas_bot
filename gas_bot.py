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

# --- Car Data ---
CARS = [
    {"name": "Yellow Subaru", "mpg": 20},
    {"name": "Black Subaru", "mpg": 20},
    {"name": "Grey Subaru", "mpg": 20},
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

def format_balance_message(users_with_miles, car_data, interaction):
    message = ""

    # Nickname mapping with specified order
    nickname_mapping = {
        "858864178962235393": "Abbas",  # mrmario
        "513552727096164378": "Sajjad",  # oneofzero
        "758778170421018674": "Jafar",  # agakatulu
        "838206242127085629": "Mosa",  # Yoshisaki
        "393241098002235392": "Ali",  # Agent
    }

    message += "### Current Amounts Owed\n"
    message += "```\n"
    for user_id in nickname_mapping: # iterate through user ids in the specified order
        if user_id in users_with_miles:
           user_data = users_with_miles[user_id]
           nickname = nickname_mapping.get(user_id, user_data.get("name", "Unknown User")) # Get the nickname or default name
           message += f"{nickname}: ${user_data['total_owed']:.2f}\n"
    message += "```\n"

    message += "### Car Status and Costs\n"
    message += "```\n"
    for car_name, car_info in car_data.items():
        message += f"{car_name}: Cost/Mile: ${car_info['cost_per_mile']:.2f}"
        if car_info['near_empty']:
             message += " (Near Empty)"
        message += "\n"
    message += "```\n"

    message += "### Total Miles Driven by User\n"
    message += "```\n"
    for user_id in nickname_mapping:
        if user_id in users_with_miles:
           user_data = users_with_miles[user_id]
           nickname = nickname_mapping.get(user_id, user_data.get("name", "Unknown User")) # Get the nickname or default name
           message += f"{nickname}: {user_data['total_miles']:.2f} miles\n"
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
    return cur.fetchone()[0] if cur.fetchone() else None

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
          "car_usage": json.loads(row[4]) if row[4] else {}
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

def record_drive(conn, user_id, user_name, car_name, distance, cost, near_empty, timestamp_iso):
    cur = conn.cursor()
    cur.execute("CALL record_drive_func(%s, %s, %s, %s, %s, %s, %s)", (user_id, user_name, car_name, distance, cost, near_empty, timestamp_iso))
    conn.commit()

def record_fill(conn, user_id, user_name, car_name, amount, price_per_gallon, payment_amount, timestamp_iso, payer_id=None):
    cur = conn.cursor()
    cur.execute("CALL record_fill_func(%s, %s, %s, %s, %s, %s, %s, %s)", (user_id, user_name, car_name, amount, price_per_gallon, payment_amount, timestamp_iso, payer_id))
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
    cur.execute("SELECT * FROM get_car_data_func()")
    car_data = {}
    for row in cur.fetchall():
        car_data[row[0]] = {"cost_per_mile": row[1], "near_empty": row[2]}
    return car_data


# --- Bot Commands ---
class CarDropdown(discord.ui.Select):
    def __init__(self, cars):
        options = [discord.SelectOption(label=car["name"], value=car["name"]) for car in cars]
        super().__init__(placeholder="Choose a car...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_car = self.values[0]
        self.view.interaction_ref = interaction  # Store interaction for later use
        if isinstance(self.view, DroveView): # Handle DroveView specific logic
            conn = get_db_connection()
            user_id = str(interaction.user.id)
            user_name = interaction.user.name
            user = get_or_create_user(conn, user_id, user_name)
            current_price = get_current_gas_price(conn) # No longer used

            car_name = self.view.selected_car
            car_data = next((car for car in CARS if car["name"] == self.view.selected_car), None)

            try:
               distance_float = float(self.view.distance) # Get distance from view
               mpg = car_data["mpg"] if car_data else 20
               cost = calculate_cost(distance_float, mpg, current_price) #No longer used
               total_owed = user["total_owed"] + cost
               save_user_data(conn, user_id, user_name, total_owed)
               timestamp_iso = datetime.datetime.now().isoformat()
               record_drive(conn, user_id, user_name, car_name, distance_float, cost, self.view.near_empty, timestamp_iso)
               conn.close()
               last_drive_message =  f"**{user_name}**: Recorded {self.view.distance} miles driven in {car_name}. Current cost: ${cost:.2f}. {'(Near Empty)' if self.view.near_empty else ''}\n\n"
            except ValueError:
                conn.close()
                await interaction.followup.send(f"The distance value is not a valid number.", ephemeral=True) # Use follow-up here as initial response was deferred
                return

            if interaction.channel.id == TARGET_CHANNEL_ID:
               await interaction.channel.purge(limit=None)

            conn = get_db_connection()
            users_with_miles = get_all_users_with_miles(conn)
            car_data = get_car_data(conn)
            conn.close()

            message = f"{last_drive_message}"
            message += format_balance_message(users_with_miles, car_data, interaction)

            await interaction.response.edit_message(content=message, view=None) # Edit the ephemeral message to show results and remove view
        elif isinstance(self.view, FillView):
            try:
                conn = get_db_connection()
                user_id = str(interaction.user.id)
                user_name = interaction.user.name
                user = get_or_create_user(conn, user_id, user_name)
                car_name = self.view.selected_car
                price_per_gallon = self.view.price_per_gallon
                payment_amount = self.view.payment_amount
                payer_id = self.view.payer_id
                timestamp_iso = datetime.datetime.now().isoformat()
                record_fill(conn, user_id, user_name, car_name, 10, price_per_gallon, payment_amount, timestamp_iso, payer_id) # Assume 10 gallons, adjust as needed. Payment recorded.

                if payer_id:
                  payer = get_or_create_user(conn, payer_id, user_name)
                  total_owed = payer["total_owed"] - payment_amount # Reduce total owed by payment amount
                  save_user_data(conn, payer_id, user_name, total_owed)
                else:
                    total_owed = user["total_owed"] - payment_amount # Reduce total owed by payment amount
                    save_user_data(conn, user_id, user_name, total_owed)

                conn.close()

                if interaction.channel.id == TARGET_CHANNEL_ID:
                   await interaction.channel.purge(limit=None)

                conn = get_db_connection()
                users_with_miles = get_all_users_with_miles(conn)
                car_data = get_car_data(conn)
                conn.close()

                message = "Gas fill-up recorded.\n\n"
                message += format_balance_message(users_with_miles, car_data, interaction)

                await interaction.response.edit_message(content=message, view=None) # Edit the ephemeral message to show results and remove view

            except Exception as e:
                logger.error(f"Error in /filled command: {e}", exc_info=True)
                await interaction.followup.send("An error occurred while recording the gas fill-up.", ephemeral=True) # Send error as followup


class DroveView(discord.ui.View):
    def __init__(self, distance, cars):
        super().__init__()
        self.add_item(CarDropdown(cars))
        self.selected_car = None
        self.near_empty = False # Initialize near_empty as False
        self.distance = distance # Add distance to the view to pass it along
        self.interaction_ref = None

    @discord.ui.button(label="Near Empty", style=discord.ButtonStyle.secondary)
    async def near_empty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() #Defer response
        self.near_empty = not self.near_empty # Toggle near_empty
        button.style = discord.ButtonStyle.danger if self.near_empty else discord.ButtonStyle.secondary
        await interaction.edit_original_response(view=self) # Update the view to reflect button change

class FillView(discord.ui.View):
    def __init__(self, price_per_gallon, payment_amount, cars, payer=None):
        super().__init__()
        self.add_item(CarDropdown(cars))
        self.selected_car = None
        self.payment_amount = payment_amount
        self.price_per_gallon = price_per_gallon
        self.payer_id = payer
        self.interaction_ref = None

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.primary)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
      if self.selected_car and self.payment_amount is not None and self.price_per_gallon is not None:
            self.stop() # Stop listening for interactions
            await interaction.response.defer() # Acknowledge, actual response will be sent later
            self.interaction_ref = interaction # Store interaction for later use

            try:
                conn = get_db_connection()
                user_id = str(interaction.user.id)
                user_name = interaction.user.name
                user = get_or_create_user(conn, user_id, user_name)
                car_name = self.selected_car
                price_per_gallon = self.price_per_gallon
                payment_amount = self.payment_amount
                payer_id = self.payer_id
                timestamp_iso = datetime.datetime.now().isoformat()
                record_fill(conn, user_id, user_name, car_name, 10, price_per_gallon, payment_amount, timestamp_iso, payer_id) # Assume 10 gallons, adjust as needed. Payment recorded.

                if payer_id:
                  payer = get_or_create_user(conn, payer_id, user_name)
                  total_owed = payer["total_owed"] - payment_amount # Reduce total owed by payment amount
                  save_user_data(conn, payer_id, user_name, total_owed)
                else:
                    total_owed = user["total_owed"] - payment_amount # Reduce total owed by payment amount
                    save_user_data(conn, user_id, user_name, total_owed)

                conn.close()

                if interaction.channel.id == TARGET_CHANNEL_ID:
                   await interaction.channel.purge(limit=None)

                conn = get_db_connection()
                users_with_miles = get_all_users_with_miles(conn)
                car_data = get_car_data(conn)
                conn.close()

                message = "Gas fill-up recorded.\n\n"
                message += format_balance_message(users_with_miles, car_data, interaction)

                await interaction.followup.send(message) # Send followup

            except Exception as e:
                logger.error(f"Error in /filled command: {e}", exc_info=True)
                await interaction.followup.send("An error occurred while recording the gas fill-up.", ephemeral=True) # Send error as followup

      else:
            await interaction.response.send_message("Please select a car and enter payment amount and price per gallon.", ephemeral=True)

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
@app_commands.describe(price_per_gallon="Price per gallon", payment_amount="Amount paid for fill", payer="Optional: User who paid for the fill")
async def filled(interaction: discord.Interaction, price_per_gallon: float, payment_amount: float, payer: discord.User = None):
    """Records gas fill-up, payment, and updates gas price."""
    payer_id = str(payer.id) if payer else None
    fill_view = FillView(price_per_gallon, payment_amount, CARS, payer_id)
    await interaction.response.send_message("Which car did you fill up?", view=fill_view, ephemeral=True)

@client.tree.command(name="drove")
@app_commands.describe(distance="Distance driven in miles")
async def drove(interaction: discord.Interaction, distance: str):
    """Logs miles driven and calculates cost using the current gas price, deletes all messages then provides the balance"""
    view = DroveView(distance, CARS)
    await interaction.response.send_message("Which car did you drive and were you near empty?", view=view, ephemeral=True) # Send ephemeral message to get car selection

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
    await interaction.response.defer() # Defer response as it might take longer
    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        car_data = get_car_data(conn)
        conn.close()

        message = format_balance_message(users_with_miles, car_data, interaction)

        await interaction.followup.send(message)
    except Exception as e:
        logger.error(f"Error in /allbalances command: {e}", exc_info=True)
        await interaction.followup.send("An error occurred while displaying balances.", ephemeral=True)

@client.tree.command(name="car_usage")
async def car_usage(interaction: discord.Interaction):
    """Displays car usage data."""
    await interaction.response.defer() # Defer response as it might take longer
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
    await interaction.response.defer() # Defer response
    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn) #Get user list before settling to iterate through
        for user_id, user_data in users_with_miles.items():
            user_name = user_data["name"]
            get_or_create_user(conn, user_id, user_name) # Ensure user exists
            save_user_data(conn, user_id, user_name, 0) # Reset balance to 0
        conn.close()

        if interaction.channel.id == TARGET_CHANNEL_ID:
           await interaction.channel.purge(limit=None)

        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        car_data = get_car_data(conn)
        conn.close()

        message = "Balances have been settled to zero.\n\n"
        message += format_balance_message(users_with_miles, car_data, interaction)

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

*   `/filled` **price_per_gallon** **payment_amount** (optional **payer**):  Records gas fill-up, payment, and updates car cost per mile. Prompts for car selection.
    *   **price_per_gallon:** The price per gallon.
    *   **payment_amount:** The amount you paid for the fill-up.
    *   **payer:** (Optional) The user who paid for the fill-up.
*   `/drove` **distance**: Records the miles driven by a user, prompts for car selection and near empty status.
    *   **distance**: The distance driven in miles.
*   `/balance`: Shows your current balance (how much you owe or are owed) - *ephemeral, only visible to you*.
*   `/allbalances`: Shows balances of all users, total miles driven, car cost per mile, and car near empty status.
*   `/car_usage`: Shows car usage data.
*   `/settle`: Resets everyone's balance to zero.
*   `/help`: Displays this help message.

**Example Usage:**

1. **Record Fill-up & Payment:**
    `/filled 3.50 35` (Records fill-up with price $3.50/gallon, payment $35, and prompts for car selection)
    `/filled 3.50 35 payer:@UserName` (Records fill-up with price $3.50/gallon, payment $35, and prompts for car selection, attributing the payment to the specified user)
2. **Driving:**
     `/drove 50` (Bot will prompt you to select a car and near empty status)
4. **Check Balance:**
    `/balance` (Shows your current balance - only visible to you)
    `/allbalances` (Shows all balances and car activities)

**Important Notes:**

*   Use `/filled` to record fill-ups and payments, and update the car cost per mile.
*   When using `/drove`, select the car you drove and indicate if it was near empty.
*   `/settle` resets all balances to zero.
*   `/balance` is ephemeral and only visible to you for privacy.
*   The `payer` argument in `/filled` is optional. If no payer is specified, the user executing the command is assumed to be the payer.

If you have any questions, feel free to ask!
"""
    await interaction.response.send_message(help_message, ephemeral=True) #Ephemeral help message

# --- Function to start the bot ---
async def main():
    await client.start(BOT_TOKEN)

# --- Run the Bot ---
if __name__ == "__main__":
    asyncio.run(main())
