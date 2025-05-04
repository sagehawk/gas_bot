# Discord Gas Tracking Bot

This Discord bot helps track shared car gas expenses within a group. It allows users to log drives using simple numeric or location-based commands, record gas fill-ups, manage payments, and view individual and group balances in a dedicated channel. The bot uses a PostgreSQL database for data persistence and is designed to be easily deployed on platforms like Railway.

![Demo](https://i.imgur.com/bsNL5c6.gif)

## Features

*   **Simplified Drive Logging:** Record miles driven using intuitive commands like `/5` (for 5 miles), `/15 decimal: 5` (for 15.5 miles), or location shortcuts like `/pnc`. Prompts for car selection.
*   **Location Shortcuts:** Predefined commands for common destinations (e.g., `/lifetime`, `/depaul`) automatically log the correct mileage.
*   **Gas Fill-Up Recording:** Tracks gas fill-ups, including the total payment amount and optionally who paid. Prompts for car selection.
*   **Balance Tracking:** Calculates and displays how much each user owes or is owed based on drives and payments.
*   **Individual Balances:** Allows users to check their personal balances privately (ephemeral message).
*   **Group Balances:** Displays all users' balances in a designated channel, automatically clearing previous messages for an up-to-date view.
*   **Settlement:** Resets all balances to zero, useful for periodic settlements. Clears and updates the designated channel.
*   **Database Persistence:** Utilizes PostgreSQL for storing all user, car, drive, fill-up, and payment information.
*   **Dedicated Channel Updates:** The bot automatically deletes old messages and posts fresh balance summaries in a specific target channel after drives, fills, or balance requests.
*   **Help Command:** Provides easy-to-understand usage instructions for all commands.

## Getting Started

### Prerequisites

*   **Discord Account:** You'll need a Discord account to create a bot application.
*   **Discord Server:** You'll need a Discord server where you want to use the bot.
*   **Python 3.7+:** Make sure you have Python 3.7 or newer installed.
*   **PostgreSQL Database:** You need a PostgreSQL database instance (e.g., using Railway, Supabase, or self-hosted).
*   **(Optional) Railway Account:** If using railway.com for hosting: [https://railway.com?referralCode=SZ07vS](https://railway.com?referralCode=SZ07vS)

### Setup Steps

1.  **Create a Discord Bot Application:**
    *   Go to the [Discord Developer Portal](https://discord.com/developers/applications).
    *   Click "New Application," give it a name, and click "Create."
    *   Navigate to the "Bot" tab. Click "Add Bot" and confirm.
    *   **Enable Privileged Gateway Intents:** Ensure `PRESENCE INTENT`, `SERVER MEMBERS INTENT`, and `MESSAGE CONTENT INTENT` are enabled under the "Bot" tab.
    *   Copy the bot's **token** (under the Bot tab, click "Reset Token" if needed). Keep this secret!
    *   Go to the "OAuth2" tab -> "URL Generator". Select scopes: `bot` and `applications.commands`.
    *   Under "Bot Permissions," select necessary permissions like: `Read Messages/View Channels`, `Send Messages`, `Manage Messages` (needed for purging the target channel).
    *   Copy the generated URL, paste it into your browser, select your server, and authorize the bot.

2.  **Set Up the PostgreSQL Database:**
    *   Create a PostgreSQL database instance (e.g., via Railway, Supabase, etc.).
    *   Connect to your database using a tool like `psql` or a GUI client (e.g., pgAdmin, DBeaver).
    *   Run the following SQL statements to create the necessary tables and functions/procedures. This structure stores users, cars, drives, fills, payments, and provides functions for efficient data retrieval and recording.
        ```sql
        -- Users Table: Stores user IDs, names, and their current balance
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY, -- Discord User ID
            name TEXT NOT NULL,
            total_owed DECIMAL DEFAULT 0
        );

        -- Cars Table: Stores car details
        CREATE TABLE IF NOT EXISTS cars (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL, -- e.g., "Subaru", "Mercedes"
            mpg INTEGER NOT NULL     -- Miles Per Gallon
        );

        -- Gas Prices Table (Optional but used by calculation logic): Stores historical gas prices
        CREATE TABLE IF NOT EXISTS gas_prices (
            id SERIAL PRIMARY KEY,
            price DECIMAL NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        -- Insert a default starting price if needed:
        -- INSERT INTO gas_prices (price) VALUES (3.50) ON CONFLICT DO NOTHING;

        -- Payments Table: Records direct payments made (could be used for manual adjustments, currently linked to fills)
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            payer_id BIGINT NOT NULL,   -- User who made the payment
            payer_name TEXT NOT NULL,
            amount DECIMAL NOT NULL,
            FOREIGN KEY (payer_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- Drives Table: Logs individual drives
        CREATE TABLE IF NOT EXISTS drives (
           id SERIAL PRIMARY KEY,
           timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
           user_id BIGINT NOT NULL,       -- User who drove
           user_name TEXT NOT NULL,
           car_id INTEGER NOT NULL,       -- Which car was driven
           distance DECIMAL NOT NULL,     -- Miles driven
           cost DECIMAL NOT NULL,         -- Calculated cost of the drive
           near_empty BOOLEAN DEFAULT FALSE, -- (Currently not set by commands, but field exists)
           FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
           FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE
        );

        -- Fills Table: Logs gas fill-ups
        CREATE TABLE IF NOT EXISTS fills (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            user_id BIGINT NOT NULL,       -- User who initiated the fill record
            user_name TEXT NOT NULL,
            car_id INTEGER NOT NULL,       -- Which car was filled
            amount DECIMAL NOT NULL,       -- Gallons filled (Currently set to 0 by bot)
            price_per_gallon DECIMAL NOT NULL, -- Price per gallon (Currently set to 0 by bot)
            payment_amount DECIMAL NOT NULL, -- Total amount paid for the fill
            payer_id BIGINT,             -- User who actually paid (can be different from user_id)
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE,
            FOREIGN KEY (payer_id) REFERENCES users(id) ON DELETE SET NULL -- Allow payer to be optional/deleted
        );

        -- Function: Get User Data with Miles and Car Usage Aggregates
        -- Retrieves user info, total owed, total miles, and a JSON breakdown of miles/fills per car
        CREATE OR REPLACE FUNCTION get_all_users_with_miles_and_car_usage_func()
        RETURNS TABLE (
          user_id BIGINT,
          user_name TEXT,
          total_owed DECIMAL,
          total_miles DECIMAL,
          car_usage JSON
        )
        AS $$
        BEGIN
          RETURN QUERY
          SELECT
            u.id,
            u.name,
            u.total_owed,
            COALESCE(SUM(d.distance), 0) AS total_miles,
            (SELECT json_agg(row_to_json(usage))
            FROM (
                SELECT
                 c.name AS car_name,
                 COALESCE(SUM(d_inner.distance), 0) as miles,
                 COALESCE(SUM(f_inner.payment_amount), 0) as fill_amount -- Sum fill payments associated with user & car
                FROM cars c
                LEFT JOIN drives d_inner ON d_inner.car_id = c.id AND d_inner.user_id = u.id
                LEFT JOIN fills f_inner ON f_inner.car_id = c.id AND f_inner.payer_id = u.id -- Check payer_id for fill amount credit
                GROUP BY c.name
            ) as usage WHERE usage.miles > 0 OR usage.fill_amount > 0) -- Only include cars used or paid for
            AS car_usage
          FROM
            users u
          LEFT JOIN
            drives d ON d.user_id = u.id
          GROUP BY
            u.id, u.name, u.total_owed;
        END;
        $$ LANGUAGE plpgsql;

        -- Procedure: Record a Drive
        -- Inserts a drive record and updates user's total_owed balance
        CREATE OR REPLACE PROCEDURE record_drive_func(
            p_user_id BIGINT,
            p_user_name TEXT,
            p_car_id INTEGER, -- Changed from car_name for direct use
            p_distance DECIMAL,
            p_cost DECIMAL,
            p_near_empty BOOLEAN,
            p_timestamp TIMESTAMP WITH TIME ZONE
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Insert the drive record
            INSERT INTO drives (timestamp, user_id, user_name, car_id, distance, cost, near_empty)
            VALUES (p_timestamp, p_user_id, p_user_name, p_car_id, p_distance, p_cost, p_near_empty);

            -- Update the user's balance (they owe the cost of the drive)
            UPDATE users SET total_owed = total_owed + p_cost WHERE id = p_user_id;

            -- Ensure user exists (handle case where user might not be in users table yet)
            INSERT INTO users (id, name, total_owed)
            VALUES (p_user_id, p_user_name, p_cost)
            ON CONFLICT (id) DO NOTHING; -- If user exists, the UPDATE above handled it
        END;
        $$;

       -- Procedure: Record a Fill
       -- Inserts a fill record and updates balances: reduces payer's owed amount, distributes cost among users
        CREATE OR REPLACE PROCEDURE record_fill_func(
            p_user_id BIGINT,           -- User who ran the command
            p_user_name TEXT,
            p_car_name TEXT,            -- Name of the car filled
            p_amount DECIMAL,           -- Gallons (currently unused/set to 0 by bot)
            p_price_per_gallon DECIMAL, -- Price per gallon (currently unused/set to 0 by bot)
            p_payment_amount DECIMAL,   -- The total amount paid
            p_timestamp TIMESTAMP WITH TIME ZONE,
            p_payer_id BIGINT DEFAULT NULL -- The Discord ID of the user who actually paid
        )
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v_car_id INTEGER;
          v_payer_id BIGINT;
          v_num_users INTEGER;
          v_cost_per_user DECIMAL;
          v_actual_payer_name TEXT;
        BEGIN
          -- Find the car ID
          SELECT id INTO v_car_id FROM cars WHERE name = p_car_name;
          IF v_car_id IS NULL THEN
            RAISE EXCEPTION 'Car % not found', p_car_name;
          END IF;

          -- Determine the payer ID (use command user if specific payer not provided)
          v_payer_id := COALESCE(p_payer_id, p_user_id);

          -- Get the name of the actual payer
          SELECT name INTO v_actual_payer_name FROM users WHERE id = v_payer_id;
          IF v_actual_payer_name IS NULL THEN
             -- If payer isn't in the system, add them (use command user's name as fallback)
             INSERT INTO users (id, name, total_owed) VALUES (v_payer_id, p_user_name, 0)
             ON CONFLICT (id) DO NOTHING;
             SELECT name INTO v_actual_payer_name FROM users WHERE id = v_payer_id; -- Try again
          END IF;


          -- Insert the fill record
          INSERT INTO fills (timestamp, user_id, user_name, car_id, amount, price_per_gallon, payment_amount, payer_id)
          VALUES (p_timestamp, p_user_id, p_user_name, v_car_id, p_amount, p_price_per_gallon, p_payment_amount, v_payer_id);

          -- Optional: Insert into payments table as well? Decide if this is needed redundancy.
          -- INSERT INTO payments (timestamp, payer_id, payer_name, amount) VALUES (p_timestamp, v_payer_id, v_actual_payer_name, p_payment_amount);

          -- Update Balances:
          -- 1. Credit the payer: Reduce their owed amount by the full payment
          UPDATE users SET total_owed = total_owed - p_payment_amount WHERE id = v_payer_id;

          -- 2. Distribute the cost among all users equally
          --    (Alternatively, could distribute based on recent usage - more complex)
          SELECT COUNT(*) INTO v_num_users FROM users;
          IF v_num_users > 0 THEN
            v_cost_per_user := p_payment_amount / v_num_users;
            UPDATE users SET total_owed = total_owed + v_cost_per_user;
          END IF;

        END;
        $$;

        -- (Optional) Function: Get Car Data (MPG, last price, near empty status)
        -- This seems unused by the current bot commands but might be useful
        CREATE OR REPLACE FUNCTION get_car_data_func()
        RETURNS TABLE (
          car_name TEXT,
          cost_per_mile DECIMAL,
          near_empty BOOLEAN
        )
        AS $$
        DECLARE
          latest_price DECIMAL;
        BEGIN
          -- Get the most recent gas price recorded
          SELECT price INTO latest_price FROM gas_prices ORDER BY timestamp DESC LIMIT 1;
          IF latest_price IS NULL THEN
             latest_price := 3.50; -- Default if no price recorded
          END IF;

          RETURN QUERY
          SELECT
            c.name,
            -- Calculate cost per mile based on latest price and car MPG
            (latest_price / NULLIF(c.mpg, 0)) AS cost_per_mile,
            -- Check if any recent drive for this car was marked near_empty
            EXISTS (
              SELECT 1
              FROM drives d
              WHERE d.car_id = c.id AND d.near_empty = TRUE
                -- Optional: Add a time constraint, e.g., AND d.timestamp > NOW() - INTERVAL '7 days'
            ) AS near_empty
          FROM cars c
          ORDER BY c.name;
        END;
        $$ LANGUAGE plpgsql;

      ```
    *   **Note the DATABASE_URL** provided by your database provider. You'll need this connection string.

3.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

4.  **Install Dependencies:**
    *   Ensure you have a `requirements.txt` file. It should contain at least:
        ```txt
        discord.py>=2.0.0
        psycopg2-binary
        # Add any other libraries your bot uses
        ```
    *   Install them:
        ```bash
        pip install -r requirements.txt
        ```

5.  **Configure Environment Variables:**
    *   Create a `.env` file in the project root (ensure it's in your `.gitignore`!) or configure environment variables directly in your hosting platform (like Railway).
    *   Add the following variables:
        ```dotenv
        BOT_TOKEN=<your_discord_bot_token>
        DATABASE_URL=<your_postgresql_database_url>
        ```
    *   Replace `<your_discord_bot_token>` with the token you copied from the Discord Developer Portal.
    *   Replace `<your_postgresql_database_url>` with your database connection string (e.g., `postgresql://user:password@host:port/database`).

6.  **IMPORTANT: Set Target Channel ID:**
    *   Open the Python bot script (e.g., `bot.py`).
    *   Find the line defining `TARGET_CHANNEL_ID`.
    *   Replace the placeholder ID (e.g., `1319440273868062861`) with the actual **Channel ID** of the Discord channel where you want the bot to post balance updates.
    *   To get a Channel ID, enable Developer Mode in Discord (User Settings > Advanced > Developer Mode), then right-click the channel name and select "Copy Channel ID".

7.  **Run the Bot:**
    ```bash
    python bot.py
    ```
    *(Assuming your main Python file is named `bot.py`)*

### Running the bot on Railway.com

*   Create a new project on Railway.
*   Choose "Deploy from GitHub repo" and select your repository.
*   Railway might detect the `python` buildpack.
*   Go to the "Variables" tab for your service.
*   Add `BOT_TOKEN` and `DATABASE_URL` secrets.
*   **Add a PostgreSQL Database Service:** Click "+ New" -> "Database" -> "PostgreSQL". Railway will automatically provide the `DATABASE_URL` variable to your bot service.
*   **Manually Run SQL:** You still need to run the SQL from Step 2 above *once* on the Railway PostgreSQL database. You can connect using the credentials provided in the Railway service's "Connect" tab.
*   **Set Target Channel ID:** You need to edit the `TARGET_CHANNEL_ID` in your code *before* deploying or redeploy after changing it.
*   The bot should now build and deploy automatically when you push changes to your linked GitHub repository branch.

## Bot Commands

The bot primarily uses slash commands (`/`).

**Drive Logging:**

*   **/0** to **/100**: Logs a drive of that specific mileage (e.g., `/8` logs 8.0 miles).
    *   `decimal: (Optional[1-9])`: Add decimal miles. Example: `/15 decimal: 5` logs **15.5 miles**.
    *   Prompts you to select the car driven. Updates balances and posts summary to the target channel.
*   **Location Shortcut Commands** (Examples - see your `LOCATION_COMMANDS` in the code for the full list):
    *   `/pnc`: Logs drive to PNC (2.0 miles).
    *   `/lifetime`: Logs drive to Life Time (14.4 miles).
    *   `/depaul`: Logs drive to DePaul (60.0 miles).
    *   ... *(and all others defined in `LOCATION_COMMANDS`)*
    *   Prompts you to select the car driven. Updates balances and posts summary to the target channel.

**Gas & Balances:**

*   **/filled** `payment:float` `[payer:user]` : Records a gas fill-up.
    *   `payment`: The **total amount paid** for the gas (e.g., `45.50`).
    *   `payer` (Optional): Mention the user who actually paid. Defaults to the user running the command.
    *   Prompts you to select the car filled. Updates balances (credits the payer, distributes cost) and posts summary to the target channel.
*   **/balance**: Shows *your* current balance (how much you owe or are owed). This message is ephemeral (only visible to you).
*   **/allbalances**: Clears the target channel and posts an updated summary of **all users' balances**.
*   **/settle**: Resets **everyone's balance to zero**. Use this when the group settles debts. Clears the target channel and posts a confirmation with zeroed balances.
*   **/help**: Displays a help message summarizing the commands (ephemeral).

**Removed Commands:**

*   `/drove` (Replaced by `/0`-`/100` and location commands)
*   `/car_usage`
*   `/note`

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change. Please ensure any code changes are reflected in the README.

## License

[MIT](LICENSE)

## Support

If you encounter any issues or have questions, please create an issue in this GitHub repository.
