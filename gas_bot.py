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
