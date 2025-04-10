# -*- coding: utf-8 -*-
import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands # Ensure this is imported
import datetime
import json
import psycopg2
from psycopg2 import sql
import logging
from collections import defaultdict # Keep if used elsewhere, maybe not needed now
import time
import random
from typing import Optional # Needed for Optional type hint

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
TARGET_CHANNEL_ID = 1319440273868062861 # Make sure this is correct

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True # Make sure you need this intent
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents) # Use commands.Bot

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO) # Set to INFO for less verbose logs, DEBUG for more
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG) # Uncomment for detailed debugging

# --- Car Data (Simplified) ---
CARS = [
    {"name": "Subaru", "mpg": 20},
    {"name": "Mercedes", "mpg": 17},
]

# --- Location Shortcut Configuration ---
LOCATION_COMMANDS = {
    "pnc": {"miles": 2.0, "location": "PNC"},
    "lifetime": {"miles": 14.4, "location": "Life Time"},
    "depaul": {"miles": 60.0, "location": "DePaul"},
    "walgreens": {"miles": 2.2, "location": "Walgreens"},
    "willowcreek": {"miles": 0.8, "location": "Willow Creek"},
    "ilyaspark": {"miles": 7.2, "location": "Ilyas Park"},
    "alibhaipark": {"miles": 2.2, "location": "Ali Bhai's Park"},
    "waterpark": {"miles": 3.2, "location": "Waterpark"},
    "dominos": {"miles": 5.8, "location": "Dominos"},
    "harper": {"miles": 7.0, "location": "Harper"},
    "bui": {"miles": 14.8, "location": "Baitul Ilm"},
    "alexianhospital": {"miles": 7.2, "location": "Alexian Hospital"},
    "woodfieldmall": {"miles": 16.2, "location": "Woodfield Mall"},
}

# --- Helper Functions ---
def calculate_cost(distance, mpg, price_per_gallon):
    """Calculates cost based on distance, mpg, and gas price."""
    if mpg is None or mpg <= 0 or price_per_gallon <= 0:
        logger.warning(f"Invalid input for cost calculation: distance={distance}, mpg={mpg}, price={price_per_gallon}")
        return 0.0
    gallons_used = distance / mpg
    cost = gallons_used * price_per_gallon
    return round(cost, 2)

def format_balance_message(users_with_miles, interaction):
    """Formats the balance message (Car notes section is removed)."""
    message = ""
    nickname_mapping = {
        "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
        "758778170421018674": "Jafar", "838206242127085629": "Mosa",
        "393241098002235392": "Ali",
    }

    message += "```\n--- Balances ---\n"
    found_users = False
    for user_id in nickname_mapping:
        if user_id in users_with_miles:
            user_data = users_with_miles[user_id]
            nickname = nickname_mapping.get(user_id, user_data.get("name", f"User {user_id}"))
            message += f"{nickname}: ${user_data.get('total_owed', 0.0):.2f}\n"
            found_users = True

    if not found_users:
        message += "No user balances found.\n"

    message += "```\n"
    return message

# --- format_car_usage_message REMOVED ---

# --- Database Functions ---
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to connect to database: {e}")
        raise # Re-raise the exception so calling code knows connection failed

def initialize_cars_in_db(conn):
    """Ensures only the desired cars exist in the DB."""
    # Keep this function as is from previous version
    cur = conn.cursor()
    desired_cars = {car["name"]: car["mpg"] for car in CARS}
    car_names_tuple = tuple(desired_cars.keys())

    try:
        # Delete cars not in the desired list
        if len(car_names_tuple) == 1:
            delete_sql = "DELETE FROM cars WHERE name != %s"
            cur.execute(delete_sql, (car_names_tuple[0],))
        elif len(car_names_tuple) > 1:
            delete_sql = sql.SQL("DELETE FROM cars WHERE name NOT IN {}").format(sql.Literal(car_names_tuple))
            cur.execute(delete_sql)
        else:
            cur.execute("DELETE FROM cars")
        logger.info(f"Deleted cars not in {list(desired_cars.keys())}. Rows affected: {cur.rowcount}")

        # Insert or update desired cars
        for name, mpg in desired_cars.items():
            cur.execute(
                """
                INSERT INTO cars (name, mpg) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET mpg = EXCLUDED.mpg;
                """,
                (name, mpg)
            )
            # logger.info(f"Ensured car '{name}' exists with MPG {mpg}") # Reduce log verbosity
        conn.commit()
        logger.info("Car initialization in DB complete.")
    except psycopg2.Error as e:
        logger.error(f"Database error during car initialization: {e}")
        conn.rollback() # Rollback on error
    finally:
        cur.close()

def get_car_id_from_name(conn, car_name):
    # Keep this function as is
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM cars WHERE name = %s", (car_name,))
        result = cur.fetchone()
        if result:
            return result[0]
        else:
            logger.error(f"Could not find car_id for car name: {car_name}")
            raise ValueError(f"Car named '{car_name}' not found in the database.")
    finally:
        cur.close()

def get_car_name_from_id(conn, car_id):
    # Keep this function as is
    if conn is None or conn.closed:
        logger.error("get_car_name_from_id: Database connection is closed or invalid.")
        return "Unknown Car"
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM cars WHERE id = %s", (car_id,))
        result = cur.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error fetching car name for ID {car_id}: {e}")
        return "Error Fetching Name"
    finally:
        if cur: cur.close()

def get_or_create_user(conn, user_id, user_name):
    # Keep this function as is
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, total_owed FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if user is None:
            cur.execute("INSERT INTO users (id, name, total_owed) VALUES (%s, %s, %s)", (user_id, user_name, 0))
            conn.commit()
            logger.info(f"Created new user: {user_name} ({user_id})")
            return {"name": user_name, "total_owed": 0.0}
        else:
            return {"name": user[0], "total_owed": float(user[1]) if user[1] is not None else 0.0}
    finally:
        cur.close()

def save_user_data(conn, user_id, user_name, total_owed):
    # Keep this function as is
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET name=%s, total_owed=%s WHERE id=%s", (user_name, total_owed, user_id))
        conn.commit()
    finally:
        cur.close()

def get_all_users_with_miles(conn):
    # Keep this function as is
    cur = conn.cursor()
    users_data = {}
    try:
        cur.execute("SELECT * FROM get_all_users_with_miles_and_car_usage_func()")
        fetched_rows = cur.fetchall()
        for row in fetched_rows:
            if len(row) >= 5:
                users_data[row[0]] = {
                    "name": row[1],
                    "total_owed": float(row[2]) if row[2] is not None else 0.0,
                    "total_miles": float(row[3]) if row[3] is not None else 0.0,
                    "car_usage": row[4] if row[4] else []
                }
            else:
                logger.warning(f"Row from get_all_users_with_miles_and_car_usage_func has unexpected structure: {row}")
    finally:
        cur.close()
    return users_data

# --- add_payment (Keep as is) ---
def add_payment(conn, payer_id, payer_name, amount):
    cur = conn.cursor()
    timestamp_iso = datetime.datetime.now().isoformat()
    try:
        cur.execute("INSERT INTO payments (timestamp, payer_id, payer_name, amount) VALUES (%s, %s, %s, %s)", (timestamp_iso, payer_id, payer_name, amount))
        conn.commit()
    finally:
        cur.close()

# --- Gas Price Functions (Keep as is) ---
def get_current_gas_price(conn):
    cur = conn.cursor()
    price_val = 3.30 # Default
    try:
        cur.execute("SELECT price FROM gas_prices ORDER BY id DESC LIMIT 1")
        price = cur.fetchone()
        if price and price[0] is not None:
            try:
                price_val = float(price[0])
            except (ValueError, TypeError):
                logger.error(f"Invalid gas price found in DB: {price[0]}. Falling back to default.")
        else:
            logger.warning("No gas price found in DB, using default: 3.30")
    finally:
        cur.close()
    return price_val

# --- record_drive (Keep as is - including location parameter) ---
def record_drive(conn, user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso, location=None):
    cur = conn.cursor()
    try:
        # Assuming your SQL function record_drive_func takes 7 arguments
        # If it takes 8 (including location), modify the call
        cur.execute("CALL record_drive_func(%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso))
        # If you need to store location and the function doesn't, you'd need an UPDATE here,
        # but that requires getting the ID of the inserted drive.
        if location:
             logger.info(f"Drive location '{location}' provided but might not be stored by record_drive_func.")
        conn.commit()
        logger.info(f"Drive recorded via func: User {user_id}, CarID {car_id}, Dist {distance}, Cost {cost}, Loc {location}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error calling record_drive_func: {e}", exc_info=True)
        raise
    finally:
        cur.close()

# --- get_car_data REMOVED ---

# --- Bot UI Elements ---

class CarDropdown(discord.ui.Select):
    """Dropdown for selecting a car during drive logging."""
    def __init__(self, distance: float, location_name: str = None):
        self.distance = distance
        self.location_name = location_name
        options = [
            discord.SelectOption(label=car["name"], description=f"{car['mpg']} MPG")
            for car in CARS
        ]
        super().__init__(placeholder="Choose the car...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        selected_car_name = self.values[0]
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        conn = None
        try:
            conn = get_db_connection()

            # --- Calculate Cost ---
            car_data = next((car for car in CARS if car["name"] == selected_car_name), None)
            if not car_data:
                await interaction.followup.send("❌ Error: Invalid car data selected.", ephemeral=True)
                return # No need to close conn here, finally block handles it

            mpg = car_data["mpg"]
            current_gas_price = get_current_gas_price(conn)
            cost = calculate_cost(self.distance, mpg, current_gas_price)

            # --- Record Drive ---
            car_id = get_car_id_from_name(conn, selected_car_name)
            record_drive(
                conn=conn, user_id=user_id, user_name=user_name, car_id=car_id,
                distance=self.distance, cost=cost, near_empty=False,
                timestamp_iso=datetime.datetime.now().isoformat(),
                location=self.location_name
            )

            # --- Get Fresh Data & Format Message ---
            users_with_miles = get_all_users_with_miles(conn)
            nickname_mapping = {
                "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
                "758778170421018674": "Jafar", "838206242127085629": "Mosa",
                "393241098002235392": "Ali",
            }
            nickname = nickname_mapping.get(user_id, user_name)

            # --- CONSTRUCT THE OUTPUT MESSAGE ---
            if self.location_name:
                 primary_message = f"**{nickname}** drove to **{self.location_name}** in a **{selected_car_name}**: **${cost:.2f}**"
            else:
                 # Format distance nicely (remove .0 if whole number)
                 distance_str = f"{self.distance:.1f}".rstrip('0').rstrip('.') if '.' in f"{self.distance:.1f}" else str(int(self.distance))
                 primary_message = f"**{nickname}** drove **{distance_str} miles** in a **{selected_car_name}**: **${cost:.2f}**"

            balance_message = format_balance_message(users_with_miles, interaction)
            full_message = primary_message + "\n\n" + balance_message

            # --- Purge and Send to Target Channel ---
            target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
            confirmation_message = "✅ Drive recorded."
            if target_channel:
                try:
                    await target_channel.purge(limit=None)
                    await target_channel.send(full_message)
                    confirmation_message = "✅ Drive recorded and message sent to channel!"
                except discord.errors.Forbidden:
                     logger.error(f"Bot lacks permissions to purge/send in channel {TARGET_CHANNEL_ID}")
                     confirmation_message = "✅ Drive recorded, but failed to update channel (permissions missing)."
                except Exception as e:
                     logger.error(f"Error purging/sending message to {TARGET_CHANNEL_ID}: {e}")
                     confirmation_message = "✅ Drive recorded, but failed to update channel (error)."
            else:
                logger.warning(f"Target channel {TARGET_CHANNEL_ID} not found.")
                confirmation_message = "✅ Drive recorded, but target channel not found."

            await interaction.followup.send(confirmation_message, ephemeral=True)

        except ValueError as e:
             logger.error(f"Value error during drive recording: {e}", exc_info=True)
             await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        except psycopg2.Error as db_err:
            logger.error(f"Database error during drive recording: {db_err}", exc_info=True)
            await interaction.followup.send("❌ A database error occurred.", ephemeral=True)
            if conn: conn.rollback()
        except Exception as e:
            logger.error(f"Unexpected error in CarDropdown callback: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
            if conn: conn.rollback()
        finally:
            if conn and not conn.closed:
                conn.close()

class DroveView(discord.ui.View):
    """View for initiating a drive record."""
    def __init__(self, distance: float, location_name: str = None, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(CarDropdown(distance=distance, location_name=location_name))

    # Keep interaction check
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        original_user_id = None
        if hasattr(interaction.message, 'interaction') and interaction.message.interaction:
            original_user_id = interaction.message.interaction.user.id
        if not original_user_id:
             logger.warning("Could not reliably determine original interaction user for drive check.")
             await interaction.response.send_message("Could not verify original command user.", ephemeral=True)
             return False
        if interaction.user.id != original_user_id:
            await interaction.response.send_message("This is not your command!", ephemeral=True)
            return False
        return True

# --- Fill related UI (CarDropdownFill, FillView) - Keep As Is ---
class CarDropdownFill(discord.ui.Select):
    def __init__(self, cars):
        options = [discord.SelectOption(label=car["name"]) for car in cars]
        super().__init__(placeholder="Choose a car...", options=options)

    async def callback(self, interaction: discord.Interaction):
        # Keep existing fill logic from previous version
        self.view.selected_car = self.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)

        conn = None
        try:
            conn = get_db_connection()
            user_id = str(interaction.user.id)
            user_name = interaction.user.display_name
            car_name = self.view.selected_car
            payment_amount = self.view.payment
            payer_id = self.view.payer # Should be string ID or None

            logger.debug(f"Fill callback - User ID: {user_id}, User Name: {user_name}, Car Name: {car_name}, Payment: {payment_amount}, Payer ID: {payer_id}")

            record_fill(
                conn=conn, user_id=user_id, user_name=user_name, car_name=car_name,
                gallons=0, price_per_gallon=0, # Dummy values
                payment_amount=payment_amount,
                timestamp_iso=datetime.datetime.now().isoformat(),
                payer_id=payer_id
            )

            # --- Get Fresh Data & Format Message ---
            users_with_miles = get_all_users_with_miles(conn)
            nickname_mapping = {
                "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
                "758778170421018674": "Jafar", "838206242127085629": "Mosa",
                "393241098002235392": "Ali",
            }
            nickname = nickname_mapping.get(user_id, user_name)

            message = f"**{nickname}** filled the **{car_name}** and paid **${payment_amount:.2f}**.\n\n"
            message += format_balance_message(users_with_miles, interaction)

            # --- Purge and Send ---
            target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
            confirmation_message = "✅ Fill recorded."
            if target_channel:
                 try:
                      await target_channel.purge(limit=None)
                      await target_channel.send(message)
                      confirmation_message = "✅ Fill recorded and message sent to channel!"
                 except discord.errors.Forbidden:
                      logger.error(f"Bot lacks permissions to purge/send in channel {TARGET_CHANNEL_ID} for fill.")
                      confirmation_message = "✅ Fill recorded, but failed to update channel (permissions missing)."
                 except Exception as e:
                      logger.error(f"Error purging/sending fill message to {TARGET_CHANNEL_ID}: {e}")
                      confirmation_message = "✅ Fill recorded, but failed to update channel (error)."
            else:
                 logger.warning(f"Target channel {TARGET_CHANNEL_ID} not found for fill.")
                 confirmation_message = "✅ Fill recorded, but target channel not found."

            await interaction.followup.send(confirmation_message, ephemeral=True)

        except psycopg2.Error as db_err:
             logger.error(f"Database error during fill recording: {db_err}", exc_info=True)
             await interaction.followup.send("❌ A database error occurred during fill.", ephemeral=True)
             if conn: conn.rollback()
        except Exception as e:
            logger.error(f"Error in fill callback: {e}", exc_info=True)
            await interaction.followup.send("❌ Failed to record fill.", ephemeral=True)
            if conn: conn.rollback()
        finally:
            if conn and not conn.closed:
                conn.close()

class FillView(discord.ui.View):
    # Keep As Is
    def __init__(self, payment, payer, timeout=180):
        super().__init__(timeout=timeout)
        self.payment = payment
        self.payer = payer
        self.selected_car = None
        self.add_item(CarDropdownFill(CARS))

    # Keep interaction check As Is
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
         original_user_id = None
         if hasattr(interaction.message, 'interaction') and interaction.message.interaction:
             original_user_id = interaction.message.interaction.user.id
         if not original_user_id:
              logger.warning("Could not reliably determine original interaction user for fill check.")
              await interaction.response.send_message("Could not verify original command user.", ephemeral=True)
              return False
         if interaction.user.id != original_user_id:
             await interaction.response.send_message("This is not your command!", ephemeral=True)
             return False
         return True

# --- NoteView, CarDropdownNote REMOVED ---

# --- Bot Commands ---

# --- Central Drive Interaction Starter ---
async def start_drive_interaction(interaction: discord.Interaction, miles: float, location_name: str = None):
    """Creates the DroveView and sends the initial ephemeral prompt."""
    if miles < 0: # Allow 0 miles now
        await interaction.response.send_message("Miles driven cannot be negative.", ephemeral=True)
        return
    # Basic check for sanity
    if miles > 10000: # Arbitrary limit
         await interaction.response.send_message("That seems like an unreasonably long drive!", ephemeral=True)
         return

    view = DroveView(distance=miles, location_name=location_name)
    await interaction.response.send_message("Which car did you drive?", view=view, ephemeral=True)

# --- /drove command REMOVED ---

# --- MODIFIED Numbered Commands Factory (/0 to /100 with optional decimal) ---
def create_number_command(miles_value: int):
    """Factory function to create numbered drive commands with optional decimal."""

    # Define the actual command coroutine function inside the factory
    @app_commands.command(name=str(miles_value), description=f"Log a drive of {miles_value} miles (+ optional .1 to .9).")
    @app_commands.describe(decimal="Add decimal miles (e.g., 5 for .5 miles)")
    async def dynamic_command(interaction: discord.Interaction,
                              # Optional argument for decimal part, restricted to 1-9
                              decimal: Optional[app_commands.Range[int, 1, 9]] = None):
        try:
            # Calculate final miles
            final_miles = float(miles_value)
            if decimal is not None:
                final_miles += decimal / 10.0

            # Call the central handler with the calculated mileage
            await start_drive_interaction(interaction, final_miles)
        except Exception as e:
             logger.error(f"Error in dynamic command /{miles_value}: {e}", exc_info=True)
             # Try to send an error message back to the user if interaction hasn't been responded to
             try:
                  await interaction.response.send_message("An error occurred processing this command.", ephemeral=True)
             except discord.errors.InteractionResponded:
                  await interaction.followup.send("An error occurred processing this command.", ephemeral=True)

    return dynamic_command # Return the coroutine function

# --- Location Commands Factory (Keep As Is) ---
def create_location_command(command_name: str, data: dict):
    """Factory function to create location-based drive commands."""
    miles_value = data["miles"]
    location_name = data["location"]

    @app_commands.command(name=command_name.lower(), description=f"Log drive to {location_name} ({miles_value} miles).")
    async def dynamic_command(interaction: discord.Interaction):
        try:
            await start_drive_interaction(interaction, miles_value, location_name)
        except Exception as e:
             logger.error(f"Error in location command /{command_name}: {e}", exc_info=True)
             try:
                  await interaction.response.send_message("An error occurred processing this command.", ephemeral=True)
             except discord.errors.InteractionResponded:
                  await interaction.followup.send("An error occurred processing this command.", ephemeral=True)

    return dynamic_command

# --- Event: on_ready ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    conn = None
    try:
        print("Connecting to database for initialization...")
        conn = get_db_connection()
        print("Initializing cars in database...")
        initialize_cars_in_db(conn)
        print("Car initialization complete.")
    except Exception as e: # Catch broader exceptions during startup DB connection
         print(f"!!! Database connection/initialization error on ready: {e}")
         # Depending on severity, you might want to exit or try reconnecting later
    finally:
        if conn and not conn.closed:
            conn.close()
            print("Database connection closed after init.")

    print("Registering dynamic commands...")
    registered_commands = 0
    # Register numbered commands /0 to /100
    # Range goes up to, but does not include, the stop value
    for i in range(0, 101):
        try:
            cmd_func = create_number_command(i)
            client.tree.add_command(cmd_func)
            registered_commands += 1
        except Exception as e:
            print(f"Error registering command /{i}: {e}")
    print(f"  Attempted to register {registered_commands} numbered commands (0-100).")

    # Register location commands
    location_commands_registered = 0
    for name, data in LOCATION_COMMANDS.items():
        try:
            cmd_func = create_location_command(name, data)
            client.tree.add_command(cmd_func)
            location_commands_registered += 1
        except Exception as e:
             print(f"Error registering location command /{name}: {e}")
    print(f"  Attempted to register {location_commands_registered} location commands.")

    # Sync commands
    try:
        # Consider syncing per guild during development for speed
        # guild_id = YOUR_GUILD_ID # Replace with your test server ID
        # synced = await client.tree.sync(guild=discord.Object(id=guild_id))
        # print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
        # Sync globally for production
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s) globally.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# --- Existing Commands (filled, balance, allbalances, settle, help) ---
# Keep the existing command functions for filled, balance, allbalances, settle
# Make sure filled uses the updated CarDropdownFill and FillView if necessary

@client.tree.command(name="filled")
@app_commands.describe(
    payment="Total payment amount (e.g., 45.50)",
    payer="Who paid? (Optional - select user)"
)
async def filled(interaction: discord.Interaction, payment: float, payer: Optional[discord.Member] = None): # Use Optional
    """Records a gas fill-up and payment."""
    if payment <= 0:
        await interaction.response.send_message("Payment amount must be positive.", ephemeral=True)
        return

    payer_member = payer if payer else interaction.user # Default to interaction user
    payer_id_str = str(payer_member.id)
    payer_display_name = payer_member.display_name

    logger.info(f"/filled: User={interaction.user.id}, Payment={payment}, Payer={payer_display_name}({payer_id_str})")

    fill_view = FillView(payment=payment, payer=payer_id_str)
    await interaction.response.send_message(
        f"Select the car filled (Payment: ${payment:.2f} by {payer_display_name}):",
        view=fill_view,
        ephemeral=True
    )

# --- record_fill (Keep As Is) ---
def record_fill(conn, user_id, user_name, car_name, gallons, price_per_gallon,
                payment_amount, timestamp_iso, payer_id=None):
    # Keep this function as is from previous version
    cur = conn.cursor()
    logger.debug(f"record_fill: user_id={user_id}, user_name={user_name}, car_name={car_name}, gallons={gallons}, price_per_gallon={price_per_gallon}, payment_amount={payment_amount}, payer_id={payer_id}, timestamp_iso={timestamp_iso}")
    try:
        cur.execute("CALL record_fill_func(%s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, user_name, car_name, float(gallons), float(price_per_gallon),
                     float(payment_amount), timestamp_iso, payer_id))
        conn.commit()
        logger.debug("record_fill_func executed successfully.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error in record_fill calling record_fill_func: {e}", exc_info=True)
        raise
    finally:
        cur.close()

# --- /note command REMOVED ---

@client.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    """Shows your personal current balance owed."""
    # Keep this command as is from previous version
    conn = None
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name
        user_data = get_or_create_user(conn, user_id, user_name)
        balance_val = user_data.get('total_owed', 0.0)
        await interaction.response.send_message(f"Your current balance is: **${balance_val:.2f}**", ephemeral=True)
    except psycopg2.Error as db_err:
        logger.error(f"Database error in /balance command: {db_err}", exc_info=True)
        await interaction.response.send_message("❌ A database error occurred retrieving your balance.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /balance command: {e}", exc_info=True)
        await interaction.response.send_message("❌ An error occurred retrieving your balance.", ephemeral=True)
    finally:
        if conn and not conn.closed: conn.close()

@client.tree.command(name="allbalances")
async def allbalances(interaction: discord.Interaction):
    """Updates the main channel with the balances of all tracked users."""
    # Keep this command as is from previous version
    await interaction.response.defer(thinking=True, ephemeral=True) # Defer ephemerally initially
    conn = None
    target_channel_id = TARGET_CHANNEL_ID # Use constant
    target_channel = interaction.guild.get_channel(target_channel_id) if interaction.guild else None
    sent_publicly = False

    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        message = format_balance_message(users_with_miles, interaction)

        if target_channel:
            try:
                await target_channel.purge(limit=None)
                await target_channel.send(message)
                await interaction.followup.send(f"✅ Balances updated in <#{target_channel_id}>.", ephemeral=True)
                sent_publicly = True
            except discord.errors.Forbidden:
                logger.error(f"Bot lacks permissions to purge/send in channel {target_channel_id} for allbalances.")
                await interaction.followup.send(f"⚠️ Balances retrieved, but couldn't update <#{target_channel_id}> (Permissions missing).\n{message}", ephemeral=True)
            except Exception as e:
                logger.error(f"Error purging/sending allbalances message to {target_channel_id}: {e}")
                await interaction.followup.send(f"⚠️ Balances retrieved, but failed to update <#{target_channel_id}> (Error).\n{message}", ephemeral=True)
        else:
            logger.warning(f"Target channel {target_channel_id} not found for allbalances.")
            await interaction.followup.send(f"⚠️ Target channel <#{target_channel_id}> not found. Displaying balances here:\n{message}", ephemeral=True)

    except psycopg2.Error as db_err:
        logger.error(f"Database error in /allbalances command: {db_err}", exc_info=True)
        await interaction.followup.send("❌ A database error occurred retrieving balances.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /allbalances command: {e}", exc_info=True)
        await interaction.followup.send("❌ An error occurred displaying balances.", ephemeral=True)
    finally:
        if conn and not conn.closed: conn.close()


# --- /car_usage command REMOVED ---


@client.tree.command(name="settle")
async def settle(interaction: discord.Interaction):
    """Resets all user balances to zero."""
    # Keep this command as is from previous version
    await interaction.response.defer(thinking=True, ephemeral=True)
    conn = None
    target_channel_id = TARGET_CHANNEL_ID
    target_channel = interaction.guild.get_channel(target_channel_id) if interaction.guild else None

    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)
        logger.info(f"Settling balances for {len(users_with_miles)} users...")
        for user_id, user_data in users_with_miles.items():
            user_name = user_data["name"]
            save_user_data(conn, user_id, user_name, 0)
            logger.info(f"Reset balance for user {user_name} ({user_id})")

        users_with_miles_reset = get_all_users_with_miles(conn) # Fetch again to show 0 balances
        message = "**Balances have been settled to zero.**\n\n"
        message += format_balance_message(users_with_miles_reset, interaction)

        if target_channel:
             try:
                 await target_channel.purge(limit=None)
                 await target_channel.send(message)
                 await interaction.followup.send(f"✅ Balances settled and updated in <#{target_channel_id}>.", ephemeral=True)
             except discord.errors.Forbidden:
                 logger.error(f"Bot lacks permissions to purge/send in channel {target_channel_id} for settle.")
                 await interaction.followup.send(f"⚠️ Balances settled, but couldn't update <#{target_channel_id}> (Permissions missing).\n{message}", ephemeral=True)
             except Exception as e:
                 logger.error(f"Error purging/sending settle message to {target_channel_id}: {e}")
                 await interaction.followup.send(f"⚠️ Balances settled, but failed to update <#{target_channel_id}> (Error).\n{message}", ephemeral=True)
        else:
             logger.warning(f"Target channel {target_channel_id} not found for settle.")
             await interaction.followup.send(f"⚠️ Balances settled (Target channel <#{target_channel_id}> not found).\n{message}", ephemeral=True)

    except psycopg2.Error as db_err:
        logger.error(f"Database error during /settle: {db_err}", exc_info=True)
        await interaction.followup.send("❌ A database error occurred while settling balances.", ephemeral=True)
        if conn: conn.rollback()
    except Exception as e:
        logger.error(f"Error in /settle command: {e}", exc_info=True)
        await interaction.followup.send("❌ An error occurred while settling balances.", ephemeral=True)
        if conn: conn.rollback()
    finally:
        if conn and not conn.closed: conn.close()

# --- MODIFIED Help Command ---
@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Provides instructions on how to use the Gas Bot."""
    help_message = f"""
**Gas Bot User Manual**

Tracks gas expenses, driving, and calculates balances. Most results posted in <#{TARGET_CHANNEL_ID}>.

**Mileage Commands (`/0` to `/100`):**
*   Use `/0`, `/1`, `/2` ... `/100` to log drives of that mileage.
*   **Optional Decimal:** Add a decimal from .1 to .9 using the `decimal` option.
    *   Example: `/15` `decimal: 5` logs a drive of **15.5 miles**.
    *   Example: `/8` logs a drive of **8.0 miles**.
*   You will be prompted to select the car (Subaru or Mercedes).

**Location Shortcut Commands:**
*   Use these commands to log drives to common locations:
"""
    # Dynamically add location commands to help message
    loc_help = []
    for cmd_name, data in sorted(LOCATION_COMMANDS.items()):
        loc_help.append(f"    *   `/{cmd_name}` - Drive to {data['location']} ({data['miles']} miles)")
    help_message += "\n".join(loc_help)

    help_message += f"""

**Other Commands:**

*   `/filled` **payment** [payer]: Records a gas fill-up. Select the car filled.
    *   `payment`: Amount paid (e.g., `42.75`).
    *   `payer`: (Optional) User who paid (defaults to you).
*   `/balance`: Shows *your* current balance (ephemeral - only you see this).
*   `/allbalances`: Updates the main channel (<#{TARGET_CHANNEL_ID}>) with everyone's current balance.
*   `/settle`: Resets **all user balances to zero**. Use with caution!
*   `/help`: Displays this help message (ephemeral).

**Removed Commands:** `/drove`, `/note`, `/car_usage`
"""
    await interaction.response.send_message(help_message, ephemeral=True)

# --- Function to start the bot (Keep As Is) ---
async def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN environment variable not set.")
        return
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable not set.")
        return
    async with client:
         await client.start(BOT_TOKEN)

# --- Run the Bot (Keep As Is) ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down...")
    except psycopg2.OperationalError as db_fail:
        # Catch potential DB connection errors during startup more gracefully
        print(f"\nFATAL: Could not connect to database on startup: {db_fail}")
        print("Please check DATABASE_URL environment variable and database status.")
    except Exception as startup_err:
        print(f"\nFATAL: An unexpected error occurred during bot startup: {startup_err}")
