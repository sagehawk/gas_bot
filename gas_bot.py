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
# DATABASE_NAME = "railway" # This wasn't used as DATABASE_URL is primary
TARGET_CHANNEL_ID = 1319440273868062861 # Make sure this is correct

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents) # Use commands.Bot as you had

# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# --- Car Data (Simplified as requested) ---
# This list is now mainly used for the dropdown options and client-side MPG lookup
# The database 'cars' table is the source of truth for MPG in some parts (like initialize_cars_in_db)
# Ensure MPG here matches the database (Subaru=20, Mercedes=17)
CARS = [
    {"name": "Subaru", "mpg": 20},
    {"name": "Mercedes", "mpg": 17},
]

# --- Location Shortcut Configuration (NEW) ---
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
    "bui": {"miles": 14.8, "location": "Baitul Ilm"}, # Using full name as requested
    "alexianhospital": {"miles": 7.2, "location": "Alexian Hospital"}, # Added
    "woodfieldmall": {"miles": 16.2, "location": "Woodfield Mall"}, # Added
}


# --- Helper Functions ---
def calculate_cost(distance, mpg, price_per_gallon):
    """Calculates cost based on distance, mpg, and gas price."""
    if mpg is None or mpg <= 0 or price_per_gallon <= 0:
        logger.warning(f"Invalid input for cost calculation: distance={distance}, mpg={mpg}, price={price_per_gallon}")
        return 0.0 # Avoid division by zero or invalid cost
    gallons_used = distance / mpg
    cost = gallons_used * price_per_gallon
    return round(cost, 2) # Round to 2 decimal places for currency


# --- MODIFIED format_balance_message ---
def format_balance_message(users_with_miles, interaction):
    """Formats the balance message, REMOVING the car notes section."""
    message = ""

    # Nickname mapping with specified order (Keep your original mapping)
    nickname_mapping = {
        "858864178962235393": "Abbas",
        "513552727096164378": "Sajjad",
        "758778170421018674": "Jafar",
        "838206242127085629": "Mosa",
        "393241098002235392": "Ali",
    }

    message += "```\n--- Balances ---\n" # Added a header for clarity
    for user_id in nickname_mapping:
        if user_id in users_with_miles:
            user_data = users_with_miles[user_id]
            # Use nickname if available, otherwise fall back to name from DB/Discord
            nickname = nickname_mapping.get(user_id, user_data.get("name", f"User {user_id}"))
            message += f"{nickname}: ${user_data['total_owed']:.2f}\n"
        else:
            # Optionally mention users in mapping but not in data (e.g., zero balance and no activity)
             nickname = nickname_mapping.get(user_id, f"User {user_id}")
             # logger.debug(f"User {nickname} ({user_id}) not found in users_with_miles data for balance message.")
             # You could add them with $0.00 balance if desired:
             # message += f"{nickname}: $0.00\n"
             pass # Or just skip them if they have no data

    message += "```\n"

    # --- Car notes section REMOVED as requested ---
    # message += "```\n--- Car Notes ---\n"
    # conn = get_db_connection()
    # cur = conn.cursor()
    # cur.execute("SELECT name, notes FROM cars")
    # car_data = cur.fetchall()
    # conn.close()
    # for car_name, car_notes in car_data:
    #     if car_notes: # Only display if there are notes
    #        message += f"{car_name}: {car_notes}\n"
    #     else:
    #        message += f"{car_name}: No notes\n" # Or skip if no notes
    # message += "```\n"

    return message

# --- format_car_usage_message (Keep As Is) ---
def format_car_usage_message(users_with_miles):
    message = "### User Car Usage\n"
    nickname_mapping = { # Keep your mapping
        "858864178962235393": "Abbas",
        "513552727096164378": "Sajjad",
        "758778170421018674": "Jafar",
        "838206242127085629": "Mosa",
        "393241098002235392": "Ali",
    }

    for user_id in nickname_mapping:
        if user_id in users_with_miles:
            user_data = users_with_miles[user_id]
            nickname = nickname_mapping.get(user_id, user_data.get("name", "Unknown User"))
            message += f"**{nickname}**:\n"
            if user_data.get('car_usage'): # Use .get() for safety
                # Sort car usage by car name for consistency
                sorted_car_usage = sorted(user_data['car_usage'], key=lambda x: x.get('car_name', ''))
                for car_usage in sorted_car_usage:
                     # Ensure keys exist before formatting
                    car_name = car_usage.get('car_name', 'Unknown Car')
                    miles = car_usage.get('miles', 0.0)
                    fill_amount = car_usage.get('fill_amount', 0.0)
                    message += f"  > {car_name}: {miles:.2f} miles, ${fill_amount:.2f} in fills\n"
            else:
                 message += "  > No car usage recorded.\n"
            total_miles = user_data.get('total_miles', 0.0)
            message += f"  > Total miles: {total_miles:.2f}\n"
            message += "\n"
    return message


# --- Database Functions (Keep As Is, except maybe initialize_cars_in_db) ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require') # Added sslmode='require' often needed for Heroku/Railway
    return conn

def initialize_cars_in_db(conn):
    """Ensures only the desired cars exist in the DB."""
    cur = conn.cursor()
    desired_cars = {car["name"]: car["mpg"] for car in CARS}

    # Delete cars not in the desired list
    # Convert list of names to tuple for SQL IN clause
    car_names_tuple = tuple(desired_cars.keys())
    if len(car_names_tuple) == 1: # Handle single car case for SQL syntax
         delete_sql = "DELETE FROM cars WHERE name != %s"
         cur.execute(delete_sql, (car_names_tuple[0],))
    elif len(car_names_tuple) > 1:
         delete_sql = sql.SQL("DELETE FROM cars WHERE name NOT IN {}").format(sql.Literal(car_names_tuple))
         cur.execute(delete_sql)
    else: # No desired cars? Delete all (unlikely scenario)
         cur.execute("DELETE FROM cars")
    logger.info(f"Deleted cars not in {list(desired_cars.keys())}")


    # Insert or update desired cars
    for name, mpg in desired_cars.items():
        cur.execute(
            """
            INSERT INTO cars (name, mpg) VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET mpg = EXCLUDED.mpg;
            """,
            (name, mpg)
        )
        logger.info(f"Ensured car '{name}' exists with MPG {mpg}")
    conn.commit()
    cur.close() # Close cursor

def get_car_id_from_name(conn, car_name):
    cur = conn.cursor()
    cur.execute("SELECT id FROM cars WHERE name = %s", (car_name,))
    result = cur.fetchone()
    cur.close()
    if result:
        return result[0]
    else:
        logger.error(f"Could not find car_id for car name: {car_name}")
        # Handle error appropriately - maybe raise an exception or return None carefully
        raise ValueError(f"Car named '{car_name}' not found in the database.")
        # return None

# --- get_car_name_from_id (Keep As Is) ---
def get_car_name_from_id(conn, car_id):
    # Ensure connection is valid before using
    if conn is None or conn.closed:
        logger.error("get_car_name_from_id: Database connection is closed or invalid.")
        return "Unknown Car" # Or raise an error

    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM cars WHERE id = %s", (car_id,))
        result = cur.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error fetching car name for ID {car_id}: {e}")
        return "Error Fetching Name"
    finally:
        if cur:
            cur.close()


# --- get_or_create_user (Keep As Is) ---
def get_or_create_user(conn, user_id, user_name):
  cur = conn.cursor()
  cur.execute("SELECT name, total_owed FROM users WHERE id = %s", (user_id,))
  user = cur.fetchone()
  if user is None:
    cur.execute("INSERT INTO users (id, name, total_owed) VALUES (%s, %s, %s)", (user_id, user_name, 0))
    conn.commit()
    cur.close()
    return {"name": user_name, "total_owed": 0}
  else:
    cur.close()
    return {"name": user[0], "total_owed": float(user[1])} # Ensure total_owed is float

# --- save_user_data (Keep As Is) ---
def save_user_data(conn, user_id, user_name, total_owed):
  cur = conn.cursor()
  cur.execute("UPDATE users SET name=%s, total_owed=%s WHERE id=%s", (user_name, total_owed, user_id))
  conn.commit()
  cur.close()

# --- get_all_users_with_miles (Keep As Is) ---
def get_all_users_with_miles(conn):
    cur = conn.cursor()
    # Make sure this function exists in your DB and returns correct structure
    cur.execute("SELECT * FROM get_all_users_with_miles_and_car_usage_func()")
    users_data = {}
    fetched_rows = cur.fetchall()
    cur.close()
    for row in fetched_rows:
      # Assuming row structure: user_id, name, total_owed, total_miles, car_usage (jsonb/array)
      if len(row) >= 5: # Basic check for expected columns
          users_data[row[0]] = {
              "name": row[1],
              "total_owed": float(row[2]) if row[2] is not None else 0.0, # Handle None, ensure float
              "total_miles": float(row[3]) if row[3] is not None else 0.0, # Handle None, ensure float
              "car_usage": row[4] if row[4] else [] # Handle None or empty array/json
          }
      else:
          logger.warning(f"Row from get_all_users_with_miles_and_car_usage_func has unexpected structure: {row}")
    return users_data


# --- add_payment (Keep As Is, though maybe unused directly) ---
def add_payment(conn, payer_id, payer_name, amount):
    cur = conn.cursor()
    timestamp_iso = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO payments (timestamp, payer_id, payer_name, amount) VALUES (%s, %s, %s, %s)", (timestamp_iso, payer_id, payer_name, amount))
    conn.commit()
    cur.close()


# --- Gas Price Functions ---
# Keep get_current_gas_price as it's used for cost calculation
# set_current_gas_price is likely unused if fills handle cost setting differently now

def get_current_gas_price(conn):
    """Gets the most recently recorded gas price."""
    cur = conn.cursor()
    cur.execute("SELECT price FROM gas_prices ORDER BY id DESC LIMIT 1")
    price = cur.fetchone()
    cur.close()
    if price and price[0] is not None:
         # Ensure the price is treated as float
         try:
              return float(price[0])
         except (ValueError, TypeError):
              logger.error(f"Invalid gas price found in DB: {price[0]}. Falling back to default.")
              return 3.30 # Default fallback
    else:
        logger.warning("No gas price found in DB, using default: 3.30")
        return 3.30 # Default if table is empty or price is NULL

# --- record_drive (Keep As Is - relies on SQL function) ---
def record_drive(conn, user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso, location=None):
    """Calls the SQL function to record a drive, now potentially including location."""
    cur = conn.cursor()
    try:
        # Check if your record_drive_func supports location. If not, you'll need to modify it
        # or use a separate UPDATE statement after the call.
        # Assuming it takes 8 arguments now: user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso, location
        # If it only takes 7, remove 'location' from the call and handle it separately if needed.

        # Let's check the number of arguments your function expects first (example, adjust query if needed)
        # cur.execute("SELECT proargnames FROM pg_proc WHERE proname = 'record_drive_func';")
        # arg_names = cur.fetchone()
        # logger.debug(f"Arguments for record_drive_func: {arg_names}")

        # *** Adjust this call based on whether your SQL function handles location ***
        cur.execute("CALL record_drive_func(%s, %s, %s, %s, %s, %s, %s)", # Assuming 7 args for now
                    (user_id, user_name, car_id, distance, cost, near_empty, timestamp_iso))

        # If the function doesn't handle location, and you added the column, update it separately:
        # Requires knowing the 'id' of the drive just inserted, which the CALL might not return easily.
        # Alternative: Modify record_drive_func to accept and store location.
        # If location storage isn't critical, you can just skip storing it.
        # if location:
        #    logger.warning("record_drive_func might not handle 'location'. Location not stored in DB unless function is updated.")
        #    # Example (needs drive ID): cur.execute("UPDATE drives SET location = %s WHERE id = %s", (location, drive_id))


        conn.commit()
        logger.info(f"Drive recorded via func: User {user_id}, CarID {car_id}, Dist {distance}, Cost {cost}, Loc {location}")
    except Exception as e:
        conn.rollback() # Rollback on error
        logger.error(f"Error calling record_drive_func: {e}", exc_info=True)
        raise # Re-raise the exception to be caught by the caller
    finally:
        cur.close()


# --- Unused History/Getter Functions (Keep As Is or remove if truly unused) ---
# get_user_drive_history, get_user_fill_history, get_car_drive_history, etc.

# --- get_car_data (Keep As Is - used by /note maybe?) ---
def get_car_data(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, notes FROM cars WHERE name IN %s", (tuple(c['name'] for c in CARS),)) # Only fetch desired cars
    car_data = {}
    fetched_rows = cur.fetchall()
    cur.close()
    for row in fetched_rows:
        car_data[row[0]] = {"notes": row[1]}
    return car_data

# --- Bot Commands ---

# --- MODIFIED CarDropdown ---
class CarDropdown(discord.ui.Select):
    """Dropdown for selecting a car, now simplified and used for drives."""
    # Note: 'view_type' might be less relevant now if this is only for drives
    def __init__(self, distance: float, location_name: str = None):
        self.distance = distance
        self.location_name = location_name # Store location if provided by command

        # Use the simplified global CARS list for options
        options = [
            discord.SelectOption(label=car["name"], description=f"{car['mpg']} MPG")
            for car in CARS
        ]
        super().__init__(placeholder="Choose the car...", options=options, min_values=1, max_values=1)
        # self.view_type = "drove" # Hardcode or remove if only used for drives

    async def callback(self, interaction: discord.Interaction):
        # Defer immediately as processing involves DB and potentially purging
        await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally

        selected_car_name = self.values[0]
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name # Use display_name for better readability

        conn = None # Initialize conn to None
        try:
            conn = get_db_connection()

            # --- Calculate Cost ---
            car_data = next((car for car in CARS if car["name"] == selected_car_name), None)
            if not car_data:
                # This shouldn't happen if options are from CARS, but good practice to check
                await interaction.followup.send("❌ Error: Invalid car data found.", ephemeral=True)
                if conn: conn.close()
                return

            mpg = car_data["mpg"]
            current_gas_price = get_current_gas_price(conn) # Get latest gas price
            cost = calculate_cost(self.distance, mpg, current_gas_price)

            # --- Record Drive ---
            car_id = get_car_id_from_name(conn, selected_car_name) # Get ID from DB
            record_drive(
                conn=conn,
                user_id=user_id,
                user_name=user_name, # Pass user's display name
                car_id=car_id,
                distance=self.distance,
                cost=cost,
                near_empty=False, # Assuming 'False' unless specified otherwise
                timestamp_iso=datetime.datetime.now().isoformat(),
                location=self.location_name # Pass location name if available
            )

            # --- Get Fresh Data & Format Message ---
            users_with_miles = get_all_users_with_miles(conn) # Get updated balances/usage

            nickname_mapping = { # Keep your mapping
                "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
                "758778170421018674": "Jafar", "838206242127085629": "Mosa",
                "393241098002235392": "Ali",
            }
            nickname = nickname_mapping.get(user_id, user_name) # Get nickname

            # --- CONSTRUCT THE NEW OUTPUT MESSAGE ---
            if self.location_name:
                # Location command format
                 primary_message = f"**{nickname}** drove to **{self.location_name}** in a **{selected_car_name}**: **${cost:.2f}**"
            else:
                # Mileage command format (/drove, /1, /5, etc.)
                 primary_message = f"**{nickname}** drove **{self.distance} miles** in a **{selected_car_name}**: **${cost:.2f}**"

            balance_message = format_balance_message(users_with_miles, interaction) # Get formatted balances
            full_message = primary_message + "\n\n" + balance_message # Combine parts

            # --- Purge and Send to Target Channel ---
            target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
            if target_channel:
                try:
                    await target_channel.purge(limit=None) # Purge the channel
                    await target_channel.send(full_message) # Send the combined message
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

            # Send ephemeral confirmation to the user who invoked the command
            await interaction.followup.send(confirmation_message, ephemeral=True)

        except ValueError as e: # Catch specific error from get_car_id_from_name
             logger.error(f"Value error during drive recording: {e}", exc_info=True)
             await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        except psycopg2.Error as db_err:
            logger.error(f"Database error during drive recording: {db_err}", exc_info=True)
            await interaction.followup.send("❌ A database error occurred.", ephemeral=True)
            if conn: conn.rollback() # Rollback on DB error
        except Exception as e:
            logger.error(f"Unexpected error in CarDropdown callback: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
            if conn: conn.rollback() # Rollback on general error
        finally:
            if conn:
                conn.close()
            # Remove the dropdown from the original ephemeral message
            # await interaction.edit_original_response(view=None) # Already deferred, followup is used

# --- MODIFIED DroveView ---
class DroveView(discord.ui.View):
    """View specifically for initiating a drive record, holding distance/location."""
    def __init__(self, distance: float, location_name: str = None, timeout=180):
        super().__init__(timeout=timeout)
        self.distance = distance
        self.location_name = location_name
        # Pass distance and location to the dropdown
        self.add_item(CarDropdown(distance=self.distance, location_name=self.location_name))
        # self.selected_car = None # No longer needed here, handled in dropdown

    # Keep interaction check to ensure only the command user can interact
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Try to get the original interaction user ID robustly
        original_user_id = None
        if hasattr(interaction.message, 'interaction') and interaction.message.interaction:
            original_user_id = interaction.message.interaction.user.id
        # Fallback for potential edge cases (though less likely with slash commands)
        elif hasattr(interaction, 'message') and hasattr(interaction.message, '_interaction_user_id'):
             original_user_id = interaction.message._interaction_user_id

        if not original_user_id:
             logger.warning("Could not reliably determine original interaction user for check.")
             # Decide behaviour: allow anyone or deny? Denying is safer.
             await interaction.response.send_message("Could not verify original command user.", ephemeral=True)
             return False

        if interaction.user.id != original_user_id:
            await interaction.response.send_message("This is not your command!", ephemeral=True)
            return False
        return True

# --- CarDropdownFill and FillView (Keep As Is - For /filled command) ---
class CarDropdownFill(discord.ui.Select):
    def __init__(self, cars):
        # Use simplified CARS list here too for consistency
        options = [discord.SelectOption(label=car["name"]) for car in CARS]
        super().__init__(placeholder="Choose a car...", options=options)

    async def callback(self, interaction: discord.Interaction):
        # --- Keep your existing fill logic ---
        self.view.selected_car = self.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)

        conn = None
        try:
            conn = get_db_connection()
            user_id = str(interaction.user.id)
            user_name = interaction.user.display_name # Use display name
            car_name = self.view.selected_car
            payment_amount = self.view.payment
            payer_id = self.view.payer # This should be the ID string or None

            logger.debug(f"Fill callback - User ID: {user_id}, User Name: {user_name}, Car Name: {car_name}, Payment: {payment_amount}, Payer ID: {payer_id}")

            # Call your existing record_fill function
            # Make sure record_fill and its SQL counterpart (record_fill_func) are correct
            record_fill(
                conn=conn,
                user_id=user_id,
                user_name=user_name,
                car_name=car_name,
                gallons=0,  # Dummy Value (as per your original code)
                price_per_gallon=0,  # Dummy Value (as per your original code)
                payment_amount=payment_amount,
                timestamp_iso=datetime.datetime.now().isoformat(),
                payer_id=payer_id
            )

            # --- Get Fresh Data & Format Message ---
            users_with_miles = get_all_users_with_miles(conn)

            nickname_mapping = { # Keep your mapping
                "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
                "758778170421018674": "Jafar", "838206242127085629": "Mosa",
                "393241098002235392": "Ali",
            }
            nickname = nickname_mapping.get(user_id, user_name)

            # Construct fill message
            message = f"**{nickname}** filled the **{car_name}** and paid **${payment_amount:.2f}**.\n\n" # Clearer fill message
            message += format_balance_message(users_with_miles, interaction)

            # --- Purge and Send ---
            target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
            confirmation_message = "✅ Fill recorded." # Default confirmation

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
            if conn:
                conn.close()
            # await interaction.edit_original_response(view=None) # Already deferred


class FillView(discord.ui.View):
     # Keep As Is, but ensure CarDropdownFill uses updated CARS list if needed (done above)
    def __init__(self, payment, payer, timeout=180): # Added timeout
        super().__init__(timeout=timeout)
        # self.gallons = 0 # Not needed if using dummy values
        # self.price = 0 # Not needed if using dummy values
        self.payment = payment
        self.payer = payer # Should be user ID string or None
        self.selected_car = None
        self.add_item(CarDropdownFill(CARS)) # Pass simplified CARS

    # Keep interaction check As Is
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
         original_user_id = None
         if hasattr(interaction.message, 'interaction') and interaction.message.interaction:
             original_user_id = interaction.message.interaction.user.id
         elif hasattr(interaction, 'message') and hasattr(interaction.message, '_interaction_user_id'):
             original_user_id = interaction.message._interaction_user_id

         if not original_user_id:
              logger.warning("Could not reliably determine original interaction user for fill check.")
              await interaction.response.send_message("Could not verify original command user.", ephemeral=True)
              return False

         if interaction.user.id != original_user_id:
             await interaction.response.send_message("This is not your command!", ephemeral=True)
             return False
         return True


# --- NoteView and CarDropdown for Notes (Keep related logic if /note command is kept) ---
# Modify CarDropdown used by NoteView to only show simplified cars if needed.
class CarDropdownNote(discord.ui.Select): # Create a separate dropdown class for notes if needed
     def __init__(self, cars):
          options = [discord.SelectOption(label=car["name"]) for car in cars]
          super().__init__(placeholder="Choose a car for the note...", options=options)

     async def callback(self, interaction: discord.Interaction):
          self.view.selected_car = self.values[0]
          await interaction.response.defer(ephemeral=True, thinking=True)

          conn = None
          try:
               conn = get_db_connection()
               user_id = str(interaction.user.id)
               user_name = interaction.user.display_name
               car_name = self.view.selected_car
               notes = self.view.notes

               car_id = get_car_id_from_name(conn, car_name)

               cur = conn.cursor()
               cur.execute("UPDATE cars SET notes = %s WHERE id = %s", (notes, car_id))
               conn.commit()
               cur.close()

               # --- Get Fresh Data & Format Message ---
               users_with_miles = get_all_users_with_miles(conn)
               nickname_mapping = { # Keep your mapping
                   "858864178962235393": "Abbas", "513552727096164378": "Sajjad",
                   "758778170421018674": "Jafar", "838206242127085629": "Mosa",
                   "393241098002235392": "Ali",
               }
               nickname = nickname_mapping.get(user_id, user_name)

               primary_message = f"**{nickname}** added/updated note for **{car_name}**: '{notes}'" # Clearer note message
               balance_message = format_balance_message(users_with_miles, interaction) # Still show balances
               full_message = primary_message + "\n\n" + balance_message

               # --- Purge and Send ---
               target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
               confirmation_message = "✅ Note updated." # Default confirmation

               if target_channel:
                    try:
                         await target_channel.purge(limit=None)
                         await target_channel.send(full_message)
                         confirmation_message = "✅ Note updated and message sent to channel!"
                    except discord.errors.Forbidden:
                         logger.error(f"Bot lacks permissions to purge/send in channel {TARGET_CHANNEL_ID} for note.")
                         confirmation_message = "✅ Note updated, but failed to update channel (permissions missing)."
                    except Exception as e:
                         logger.error(f"Error purging/sending note message to {TARGET_CHANNEL_ID}: {e}")
                         confirmation_message = "✅ Note updated, but failed to update channel (error)."
               else:
                    logger.warning(f"Target channel {TARGET_CHANNEL_ID} not found for note.")
                    confirmation_message = "✅ Note updated, but target channel not found."

               await interaction.followup.send(confirmation_message, ephemeral=True)

          except ValueError as e: # Catch specific error from get_car_id_from_name
             logger.error(f"Value error during note update: {e}", exc_info=True)
             await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
          except psycopg2.Error as db_err:
              logger.error(f"Database error during note update: {db_err}", exc_info=True)
              await interaction.followup.send("❌ A database error occurred saving the note.", ephemeral=True)
              if conn: conn.rollback()
          except Exception as e:
              logger.error(f"Error in note callback: {e}", exc_info=True)
              await interaction.followup.send("❌ An error occurred updating the note.", ephemeral=True)
              if conn: conn.rollback()
          finally:
              if conn:
                  conn.close()
              # await interaction.edit_original_response(view=None) # Already deferred


class NoteView(discord.ui.View):
    # Keep As Is, but use CarDropdownNote
    def __init__(self, notes, timeout=180): # Added timeout
        super().__init__(timeout=timeout)
        self.add_item(CarDropdownNote(CARS)) # Use the note-specific dropdown
        self.selected_car = None
        self.notes = notes

    # Keep interaction check As Is
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
         original_user_id = None
         if hasattr(interaction.message, 'interaction') and interaction.message.interaction:
             original_user_id = interaction.message.interaction.user.id
         elif hasattr(interaction, 'message') and hasattr(interaction.message, '_interaction_user_id'):
             original_user_id = interaction.message._interaction_user_id

         if not original_user_id:
              logger.warning("Could not reliably determine original interaction user for note check.")
              await interaction.response.send_message("Could not verify original command user.", ephemeral=True)
              return False

         if interaction.user.id != original_user_id:
             await interaction.response.send_message("This is not your command!", ephemeral=True)
             return False
         return True

# --- Central Drive Interaction Starter ---
async def start_drive_interaction(interaction: discord.Interaction, miles: float, location_name: str = None):
    """Creates the DroveView and sends the initial ephemeral prompt."""
    if miles <= 0:
        await interaction.response.send_message("Miles driven must be positive.", ephemeral=True)
        return

    view = DroveView(distance=miles, location_name=location_name)
    await interaction.response.send_message("Which car did you drive?", view=view, ephemeral=True)


# --- MODIFIED /drove command ---
@client.tree.command(name="drove", description="Log miles driven (> 40 or custom) and calculate cost.")
@app_commands.describe(distance="Distance driven in miles (e.g., 45.5)")
async def drove(interaction: discord.Interaction, distance: float): # Changed distance to float directly
    """Logs a drive with a custom mile amount."""
    if distance <= 40:
         await interaction.response.send_message(f"Please use the dedicated /{int(distance)} command for distances up to 40 miles.", ephemeral=True)
         return
    # Use the central handler function
    await start_drive_interaction(interaction, distance)


# --- NEW Numbered Commands (/1 to /40) ---
def create_number_command(miles_value: int):
    """Factory function to create numbered drive commands."""
    # Define the actual command coroutine function inside the factory
    @app_commands.command(name=str(miles_value), description=f"Log a drive of {miles_value} miles.")
    async def dynamic_command(interaction: discord.Interaction):
        # Call the central handler with the fixed mileage
        await start_drive_interaction(interaction, float(miles_value)) # Ensure miles is float

    return dynamic_command # Return the coroutine function


# --- NEW Location Commands ---
def create_location_command(command_name: str, data: dict):
    """Factory function to create location-based drive commands."""
    miles_value = data["miles"]
    location_name = data["location"] # Proper capitalization for display

    # Define the actual command coroutine function inside the factory
    @app_commands.command(name=command_name.lower(), description=f"Log drive to {location_name} ({miles_value} miles).")
    async def dynamic_command(interaction: discord.Interaction):
        # Call the central handler with miles and location name
        await start_drive_interaction(interaction, miles_value, location_name)

    return dynamic_command # Return the coroutine function


# --- Event: on_ready ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    conn = None
    try:
        print("Connecting to database for initialization...")
        conn = get_db_connection()
        print("Initializing cars in database...")
        initialize_cars_in_db(conn) # Ensure only Subaru/Mercedes exist
        print("Car initialization complete.")
    except psycopg2.Error as e:
         print(f"!!! Database connection/initialization error on ready: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

    print("Registering dynamic commands...")
    registered_commands = 0
    # Register numbered commands /1 to /40
    for i in range(1, 41):
        try:
            cmd_func = create_number_command(i)
            client.tree.add_command(cmd_func) # Add command func directly
            registered_commands += 1
        except Exception as e:
            print(f"Error registering command /{i}: {e}")
    print(f"  Registered {registered_commands} numbered commands (1-40).")

    # Register location commands
    location_commands_registered = 0
    for name, data in LOCATION_COMMANDS.items():
        try:
            cmd_func = create_location_command(name, data)
            client.tree.add_command(cmd_func)
            location_commands_registered += 1
        except Exception as e:
             print(f"Error registering location command /{name}: {e}")
    print(f"  Registered {location_commands_registered} location commands.")

    # Sync commands
    try:
        # Sync globally - might take time
        synced = await client.tree.sync()
        # Or sync to a specific guild for testing (replace YOUR_GUILD_ID)
        # guild_id = 123456789012345678 # <--- REPLACE
        # synced = await client.tree.sync(guild=discord.Object(id=guild_id))
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")


# --- Keep your existing commands (filled, note, balance, allbalances, car_usage, settle, help) ---
# Make sure they function correctly with the simplified CARS list and modified DB/output formats.

@client.tree.command(name="filled")
@app_commands.describe(
    payment="Total payment amount (e.g., 45.50)",
    payer="Who paid? (Optional - select user)"
)
async def filled(interaction: discord.Interaction, payment: float, payer: discord.Member = None): # Use discord.Member for user selection
    """Records a gas fill-up and payment."""
    # Ensure payment is positive
    if payment <= 0:
        await interaction.response.send_message("Payment amount must be positive.", ephemeral=True)
        return

    # Payer ID needs to be a string for DB consistency, or None
    payer_id_str = str(payer.id) if payer else str(interaction.user.id) # Default to command user if not specified
    logger.info(f"/filled command initiated by {interaction.user.id}. Payment: {payment}, Payer specified: {payer.id if payer else 'None'}, Using Payer ID: {payer_id_str}")


    fill_view = FillView(
        payment=payment,
        payer=payer_id_str # Pass the string ID
    )
    await interaction.response.send_message(
        f"Select the car filled (Payment: ${payment:.2f} by {payer.display_name if payer else interaction.user.display_name}):",
        view=fill_view,
        ephemeral=True
    )

# --- record_fill function (Keep As Is - relies on SQL function) ---
def record_fill(conn, user_id, user_name, car_name, gallons, price_per_gallon,
                payment_amount, timestamp_iso, payer_id=None):
    """Calls the SQL function to record a fill."""
    cur = conn.cursor()
    logger.debug(f"record_fill: user_id={user_id}, user_name={user_name}, car_name={car_name}, gallons={gallons}, price_per_gallon={price_per_gallon}, payment_amount={payment_amount}, payer_id={payer_id}, timestamp_iso={timestamp_iso}")
    try:
        # Ensure your record_fill_func exists and takes these arguments in this order
        # Verify payer_id handling in the SQL function (is it nullable? correct type?)
        cur.execute("CALL record_fill_func(%s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, user_name, car_name, float(gallons), float(price_per_gallon),
                     float(payment_amount), timestamp_iso, payer_id)) # Pass payer_id
        conn.commit()
        logger.debug("record_fill_func executed successfully and committed.")
    except Exception as e:
        conn.rollback() # Rollback on error
        logger.error(f"Error in record_fill calling record_fill_func: {e}", exc_info=True)
        raise # Re-raise exception
    finally:
        cur.close()


@client.tree.command(name="note")
@app_commands.describe(notes="Any notes about the car (e.g., 'Needs oil change')")
async def note(interaction: discord.Interaction, notes: str):
    """Sets or updates a note for a specific car."""
    if not notes.strip():
         await interaction.response.send_message("Note cannot be empty.", ephemeral=True)
         return
    view = NoteView(notes)
    await interaction.response.send_message("Which car do you want to add/update the note for?", view=view, ephemeral=True)


@client.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    """Shows your personal current balance owed."""
    conn = None
    try:
        conn = get_db_connection()
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name # Use display name
        # Use get_or_create_user which handles new users and returns dict
        user_data = get_or_create_user(conn, user_id, user_name)
        balance = user_data.get('total_owed', 0.0) # Safely get balance

        await interaction.response.send_message(f"Your current balance is: **${balance:.2f}**", ephemeral=True)

    except psycopg2.Error as db_err:
        logger.error(f"Database error in /balance command: {db_err}", exc_info=True)
        await interaction.response.send_message("❌ A database error occurred while retrieving your balance.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /balance command: {e}", exc_info=True)
        await interaction.response.send_message("❌ An error occurred while retrieving your balance.", ephemeral=True)
    finally:
        if conn:
            conn.close()


@client.tree.command(name="allbalances")
async def allbalances(interaction: discord.Interaction):
    """Shows the balances of all tracked users."""
    # Defer response as DB query and formatting might take time
    await interaction.response.defer(thinking=True)
    conn = None
    try:
        conn = get_db_connection()
        users_with_miles = get_all_users_with_miles(conn)

        # Format message using the modified function (without notes)
        message = format_balance_message(users_with_miles, interaction)

        # Purge and send to the target channel
        target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
        confirmation_message = "Displayed all balances." # Default confirmation

        if target_channel:
            try:
                await target_channel.purge(limit=None)
                await target_channel.send(message)
                confirmation_message = "Updated all balances in the channel."
            except discord.errors.Forbidden:
                logger.error(f"Bot lacks permissions to purge/send in channel {TARGET_CHANNEL_ID} for allbalances.")
                confirmation_message = "Displayed all balances, but failed to update channel (permissions missing)."
                await interaction.followup.send(message) # Send in current channel as fallback
            except Exception as e:
                logger.error(f"Error purging/sending allbalances message to {TARGET_CHANNEL_ID}: {e}")
                confirmation_message = "Displayed all balances, but failed to update channel (error)."
                await interaction.followup.send(message) # Send in current channel as fallback
        else:
            logger.warning(f"Target channel {TARGET_CHANNEL_ID} not found for allbalances.")
            confirmation_message = "Displayed all balances (target channel not found)."
            await interaction.followup.send(message) # Send in current channel if target not found

        # If message wasn't sent via followup already, send confirmation
        # (This logic might need refinement depending on desired behavior)
        # await interaction.followup.send(confirmation_message, ephemeral=True) # Maybe remove this if message always sent publicly

    except psycopg2.Error as db_err:
        logger.error(f"Database error in /allbalances command: {db_err}", exc_info=True)
        await interaction.followup.send("❌ A database error occurred while retrieving balances.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /allbalances command: {e}", exc_info=True)
        await interaction.followup.send("❌ An error occurred while displaying balances.", ephemeral=True)
    finally:
        if conn:
            conn.close()


@client.tree.command(name="car_usage")
async def car_usage(interaction: discord.Interaction):
    """Displays total miles driven by each user and per car."""
    await interaction.response.defer(thinking=True)
    conn = None
    try:
      conn = get_db_connection()
      users_with_miles = get_all_users_with_miles(conn)
      message = format_car_usage_message(users_with_miles) # Format the usage stats
      await interaction.followup.send(message) # Send publicly
    except psycopg2.Error as db_err:
        logger.error(f"Database error in /car_usage command: {db_err}", exc_info=True)
        await interaction.followup.send("❌ A database error occurred retrieving car usage.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in /car_usage command: {e}", exc_info=True)
        await interaction.followup.send("❌ An error occurred displaying car usage.", ephemeral=True)
    finally:
       if conn:
            conn.close()


@client.tree.command(name="settle")
async def settle(interaction: discord.Interaction):
    """Resets all user balances to zero."""
    await interaction.response.defer(thinking=True)
    conn = None
    try:
        conn = get_db_connection()
        # Get current user data to iterate through all known users
        users_with_miles = get_all_users_with_miles(conn)
        logger.info(f"Settling balances for {len(users_with_miles)} users...")
        for user_id, user_data in users_with_miles.items():
            user_name = user_data["name"]
            # Ensure user exists (though get_all_users should only return existing ones)
            # get_or_create_user(conn, user_id, user_name)
            save_user_data(conn, user_id, user_name, 0) # Set total_owed to 0
            logger.info(f"Reset balance for user {user_name} ({user_id})")

        # Get the freshly reset balances to display
        users_with_miles_reset = get_all_users_with_miles(conn)
        message = "**Balances have been settled to zero.**\n\n"
        message += format_balance_message(users_with_miles_reset, interaction)

        # Purge and send to target channel
        target_channel = interaction.guild.get_channel(TARGET_CHANNEL_ID) if interaction.guild else None
        confirmation_message = "Balances settled."

        if target_channel:
             try:
                 await target_channel.purge(limit=None)
                 await target_channel.send(message)
                 confirmation_message = "Balances settled and message sent to channel."
             except discord.errors.Forbidden:
                 logger.error(f"Bot lacks permissions to purge/send in channel {TARGET_CHANNEL_ID} for settle.")
                 confirmation_message = "Balances settled, but failed to update channel (permissions missing)."
                 await interaction.followup.send(message) # Fallback
             except Exception as e:
                 logger.error(f"Error purging/sending settle message to {TARGET_CHANNEL_ID}: {e}")
                 confirmation_message = "Balances settled, but failed to update channel (error)."
                 await interaction.followup.send(message) # Fallback
        else:
             logger.warning(f"Target channel {TARGET_CHANNEL_ID} not found for settle.")
             confirmation_message = "Balances settled (target channel not found)."
             await interaction.followup.send(message) # Fallback

        # See note on allbalances re: sending confirmation vs public message
        # await interaction.followup.send(confirmation_message, ephemeral=True)

    except psycopg2.Error as db_err:
        logger.error(f"Database error during /settle: {db_err}", exc_info=True)
        await interaction.followup.send("❌ A database error occurred while settling balances.", ephemeral=True)
        if conn: conn.rollback() # Rollback on DB error
    except Exception as e:
        logger.error(f"Error in /settle command: {e}", exc_info=True)
        await interaction.followup.send("❌ An error occurred while settling balances.", ephemeral=True)
        if conn: conn.rollback() # Rollback on general error
    finally:
        if conn:
            conn.close()


@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Provides instructions on how to use the Gas Bot."""
    # Updated help message reflecting new commands and changes
    help_message = f"""
**Gas Bot User Manual**

Tracks gas expenses, driving, and calculates balances. All results posted in <#{TARGET_CHANNEL_ID}>.

**Core Commands:**

*   `/filled` **payment** [payer]: Records a gas fill-up. Select the car filled.
    *   `payment`: Amount paid (e.g., `42.75`).
    *   `payer`: (Optional) User who paid (defaults to you).
*   `/drove` **distance**: Records miles driven for distances **over 40 miles**. Select the car driven.
    *   `distance`: Miles driven (e.g., `55.2`).
*   `/note` **notes**: Adds/updates a note for a specific car (e.g., "Check tire pressure"). Select the car.

**Mileage Shortcut Commands (1-40 miles):**
*   Use `/1`, `/2`, `/3` ... `/40` to quickly log drives of that exact mileage.
    *   Example: `/15` - Logs a 15-mile drive. You'll be prompted to select the car.

**Location Shortcut Commands:**
*   Use these commands to log drives to common locations:
"""
    # Dynamically add location commands to help message
    loc_help = []
    for cmd_name, data in sorted(LOCATION_COMMANDS.items()):
        loc_help.append(f"    *   `/{cmd_name}` - Drive to {data['location']} ({data['miles']} miles)")
    help_message += "\n".join(loc_help)

    help_message += """

**Balance & Info Commands:**

*   `/balance`: Shows *your* current balance (ephemeral - only you see this).
*   `/allbalances`: Updates the main channel (<#{TARGET_CHANNEL_ID}>) with everyone's current balance.
*   `/car_usage`: Shows total miles driven by each user and breakdown per car.
*   `/settle`: Resets **all user balances to zero**. Use with caution!
*   `/help`: Displays this help message (ephemeral).

**Example Flow:**

1.  You drive 12 miles: `/12` -> Select Car -> Bot posts result.
2.  You drive to Woodfield Mall: `/woodfieldmall` -> Select Car -> Bot posts result.
3.  You drive 65 miles: `/drove 65` -> Select Car -> Bot posts result.
4.  You fill the Subaru for $50: `/filled 50` -> Select Subaru -> Bot posts result.
5.  Check your balance: `/balance`
6.  Update public balances: `/allbalances`
7.  End of the month/week: `/settle` (after payments are exchanged).
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
    async with client: # Use async context manager
         await client.start(BOT_TOKEN)


# --- Run the Bot (Keep As Is) ---
if __name__ == "__main__":
    # Consider adding signal handling for graceful shutdown if needed
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutting down...")
