import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

DATABASE_FILE = "gas_data.json"

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)

# --- MPG Data ---
DEFAULT_MPG = 20  # Default MPG for all calculations

# --- Gas Price Data ---
CURRENT_GAS_PRICE = 3.30  # Default gas price

# --- Data Storage (using a JSON file) ---
def load_data():
    try:
        with open(DATABASE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"fill_ups": [], "users": {}, "payments": [], "current_gas_price": CURRENT_GAS_PRICE}

def save_data(data):
    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
    data = load_data()
    data["current_gas_price"] = price_per_gallon
    save_data(data)
    await interaction.response.send_message(f"Current gas price updated to ${price_per_gallon:.2f}")

@client.tree.command(name="drove")
@app_commands.describe(distance="Distance driven in miles")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id)) # Cooldown per user per guild
async def drove(interaction: discord.Interaction, distance: float):
    """Logs miles driven and calculates cost using the current gas price."""
    data = load_data()
    user_id = str(interaction.user.id)
    user_name = interaction.user.name

    if user_id not in data["users"]:
        data["users"][user_id] = {"name": user_name, "total_owed": 0}
    else:
        data["users"][user_id]["name"] = user_name

    # Calculate cost using current gas price and default MPG
    current_price = data.get("current_gas_price", CURRENT_GAS_PRICE)
    cost = calculate_cost(distance, DEFAULT_MPG, current_price)

    # Update the user's total owed amount
    data["users"][user_id]["total_owed"] += cost

    # save the gas amount owed for the distance in a new key
    if 'distance_costs' not in data["users"][user_id]:
        data["users"][user_id]["distance_costs"] = []
    data["users"][user_id]["distance_costs"].append({
        "distance" : distance,
        "cost" : cost
    })

    save_data(data)
    await interaction.response.send_message(f"Recorded {distance} miles driven. Current cost: ${cost:.2f}")

@client.tree.command(name="balance")
async def balance(interaction: discord.Interaction):
    """Shows how much each user owes."""
    data = load_data()
    user_id = str(interaction.user.id)
    user_name = interaction.user.name

    if user_id in data["users"]:
        data["users"][user_id]["name"] = user_name
        total_owed = data["users"][user_id]["total_owed"]
        await interaction.response.send_message(f"Your current balance: ${total_owed:.2f}")
    else:
        await interaction.response.send_message("You have no recorded expenses.")

@client.tree.command(name="allbalances")
async def allbalances(interaction: discord.Interaction):
    """Shows the balances of all users."""
    data = load_data()
    message = "Current Balances:\n"
    for user_id, user_data in data["users"].items():
        # Fetch the member object to get the updated name
        member = interaction.guild.get_member(int(user_id))
        if member:
            user_name = member.name
        else:
            user_name = user_data.get("name", "Unknown User")  # Fallback to stored name or "Unknown User"

        # Update the user's name in the database
        user_data["name"] = user_name

        message += f"{user_name}: ${user_data['total_owed']:.2f}\n"
    save_data(data)
    await interaction.response.send_message(message)

@client.tree.command(name="settle")
async def settle(interaction: discord.Interaction):
    """Resets your balance to zero."""
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data["users"]:
        data["users"][user_id]["total_owed"] = 0
        save_data(data)
        await interaction.response.send_message("Your balance has been settled.")
    else:
        await interaction.response.send_message("You have no balance to settle.")

@client.tree.command(name="paid")
@app_commands.describe(amount="Amount paid")
async def paid(interaction: discord.Interaction, amount: float):
    """Records a payment made by a user."""
    data = load_data()
    payer_id = str(interaction.user.id)
    user_name = interaction.user.name

    if payer_id not in data["users"]:
        data["users"][payer_id] = {"name": user_name, "total_owed": 0}

    # Allow balance to go negative (remove the check)
    data["users"][payer_id]["total_owed"] -= amount

    data["payments"].append({
        "timestamp": datetime.datetime.now().isoformat(),
        "payer_id": payer_id,
        "payer_name": user_name,
        "amount": amount
    })

    save_data(data)
    await interaction.response.send_message(f"Payment of ${amount:.2f} recorded. Your new balance is ${data['users'][payer_id]['total_owed']:.2f}")

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
    *   **distance:** The distance driven in miles.
*   `/balance`: Shows your current balance (how much you owe or are owed).
*   `/allbalances`: Shows the balances of all users.
*   `/paid` **amount**: Records a payment you made towards your balance.
    *   **amount:** The amount paid.
*   `/settle`: Resets your balance to zero (use this after you've paid in full).
*   `/help`: Displays this help message.

**Example Usage:**

1. **Update Gas Price:**
    `/filled 3.50` (Updates the gas price to $3.50/gallon)
2. **Driving:**
    `/drove 50` (Records 50 miles driven)
3. **Payment:**
    `/paid 20` (Records a payment of $20)
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
