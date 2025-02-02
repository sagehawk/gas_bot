# Discord Gas Tracking Bot

This Discord bot helps track shared car gas expenses within a group. It allows users to log drives, record gas fill-ups, manage payments, and view individual and group balances. The bot uses a PostgreSQL database for data persistence and is designed to be easily deployed on platforms like Railway.

## Features

*   **Drive Logging:** Records miles driven by each user, associated with a specific car and optional near-empty status.
*   **Gas Fill-Up Recording:** Tracks gas fill-ups, including price per gallon, payment amount, and optionally who paid for the fill.
*   **Balance Tracking:** Calculates and displays how much each user owes or is owed.
*   **Individual Balances:** Allows users to check their personal balances (ephemeral).
*   **Group Balances:** Displays all users' balances with an overview of the car costs.
*   **Car Usage Statistics:** Shows how much each user used each car and their total miles driven.
*   **Settlement:** Resets all balances to zero, useful for periodic settlements.
*   **Database Persistence:** Utilizes PostgreSQL for storing all information.
*   **Clear Messages:** The bot automatically deletes messages in the specified channel before showing updated balances.
*   **Help Command:** Provides easy-to-understand usage instructions.

## Getting Started

### Prerequisites

*   **Discord Account:** You'll need a Discord account to create a bot application.
*   **Discord Server:** You'll need a Discord server where you want to use the bot.
*   **Python 3.7+:** Make sure you have Python 3.7 or newer installed on your system.
*   **PostgreSQL Database:** You need a PostgreSQL database instance (e.g., using Railway).
*   **Railway Account:** If you're using railway.com for hosting: [https://railway.com?referralCode=SZ07vS](https://railway.com?referralCode=SZ07vS)

### Setup Steps

1.  **Create a Discord Bot Application:**
    *   Go to the [Discord Developer Portal](https://discord.com/developers/applications).
    *   Click on "New Application."
    *   Give your bot a name and click "Create."
    *   Navigate to the "Bot" tab in the left sidebar.
    *   Click on "Add Bot" and confirm the addition.
    *   Copy the bot's **token**. (You will need this later)
    *   Under the "OAuth2" tab, go to "URL Generator". Select `bot`, `applications.commands` and then copy the generated URL and paste it into a browser. Select the server you want to add the bot to and authorize.

2.  **Set Up the PostgreSQL Database:**
    *   If you're using Railway, create a new PostgreSQL database service.
    *   You need to create the tables in your database. Run the SQL statements below using a tool like `psql` or a GUI client like pgAdmin.
        ```sql
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            total_owed DECIMAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS cars (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            mpg INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gas_prices (
            id SERIAL PRIMARY KEY,
            price DECIMAL NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            payer_id BIGINT NOT NULL,
            payer_name TEXT NOT NULL,
            amount DECIMAL NOT NULL,
              FOREIGN KEY (payer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS drives (
           id SERIAL PRIMARY KEY,
           timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            user_id BIGINT NOT NULL,
            user_name TEXT NOT NULL,
            car_id INTEGER NOT NULL,
            distance DECIMAL NOT NULL,
            cost DECIMAL NOT NULL,
            near_empty BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (car_id) REFERENCES cars(id)
        );
        CREATE TABLE IF NOT EXISTS fills (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            user_id BIGINT NOT NULL,
            user_name TEXT NOT NULL,
            car_id INTEGER NOT NULL,
            amount DECIMAL NOT NULL,
            price_per_gallon DECIMAL NOT NULL,
            payment_amount DECIMAL NOT NULL,
              payer_id BIGINT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (car_id) REFERENCES cars(id),
              FOREIGN KEY (payer_id) REFERENCES users(id)
        );

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
                 COALESCE(SUM(d.distance), 0) as miles,
                  COALESCE(SUM(f.payment_amount), 0) as fill_amount
                FROM cars c
                LEFT JOIN drives d ON d.car_id = c.id AND d.user_id = u.id
                LEFT JOIN fills f ON f.car_id = c.id AND f.user_id = u.id
                GROUP BY c.name
            ) as usage) AS car_usage
          FROM
            users u
          LEFT JOIN
            drives d ON d.user_id = u.id
          GROUP BY
            u.id, u.name, u.total_owed;
        END;
        $$ LANGUAGE plpgsql;

       CREATE OR REPLACE PROCEDURE record_drive_func(
            p_user_id BIGINT,
            p_user_name TEXT,
            p_car_name TEXT,
            p_distance DECIMAL,
            p_cost DECIMAL,
            p_near_empty BOOLEAN,
            p_timestamp TIMESTAMP WITH TIME ZONE
        )
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_car_id INTEGER;
        BEGIN
            SELECT id INTO v_car_id FROM cars WHERE name = p_car_name;

            INSERT INTO drives (timestamp, user_id, user_name, car_id, distance, cost, near_empty)
            VALUES (p_timestamp, p_user_id, p_user_name, v_car_id, p_distance, p_cost, p_near_empty);
        END;
        $$;

       CREATE OR REPLACE PROCEDURE record_fill_func(
            p_user_id BIGINT,
            p_user_name TEXT,
            p_car_name TEXT,
            p_amount DECIMAL,
            p_price_per_gallon DECIMAL,
            p_payment_amount DECIMAL,
            p_timestamp TIMESTAMP WITH TIME ZONE,
            p_payer_id BIGINT DEFAULT NULL
        )
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v_car_id INTEGER;
        BEGIN
          SELECT id INTO v_car_id FROM cars WHERE name = p_car_name;
          INSERT INTO fills (timestamp, user_id, user_name, car_id, amount, price_per_gallon, payment_amount, payer_id)
          VALUES (p_timestamp, p_user_id, p_user_name, v_car_id, p_amount, p_price_per_gallon, p_payment_amount, p_payer_id);

        END;
        $$;

       CREATE OR REPLACE FUNCTION get_car_data_func()
        RETURNS TABLE (
          car_name TEXT,
          cost_per_mile DECIMAL,
            near_empty BOOLEAN
        )
        AS $$
        BEGIN
          RETURN QUERY
          SELECT
            c.name,
              (f.price_per_gallon / c.mpg) AS cost_per_mile,
            EXISTS (
              SELECT 1
              FROM drives d
              WHERE d.car_id = c.id AND d.near_empty = TRUE
            ) AS near_empty
          FROM cars c
          LEFT JOIN fills f ON c.id = f.car_id
          ORDER BY c.name;
        END;
        $$ LANGUAGE plpgsql;

       
        ```
    *   **Note the DATABASE_URL** provided by Railway or your database provider. This will be needed.

3.  **Clone the Repository**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    Make sure you have a requirements.txt file with all needed libraries. You should have at least:
    ```
        discord.py
        psycopg2-binary
    ```

5.  **Configure Environment Variables:**
    *   Create a `.env` file (or configure environment variables in your hosting platform).
    *   Add the following variables:
        ```
        BOT_TOKEN=<your_bot_token>
        DATABASE_URL=<your_database_url>
        ```
        **Important:** Replace `<your_bot_token>` with the actual token you copied earlier and  `<your_database_url>` with your database URL.

6. **Replace Target Channel ID**
    *   Replace `TARGET_CHANNEL_ID` with your target channel in the Python code.

7.  **Run the Bot:**
    ```bash
    python bot.py
    ```
    *(Assuming your main file is named `bot.py`)*

### Running the bot on Railway.com
*   Create a new project.
*   Link your repository with git.
*   Add your required variables under variables
*   Add a PostgreSQL Database service
*   It should now automatically run when you make a change to the repo.

## Bot Commands

The bot uses slash commands, which means you can type `/` to see a list of available commands within Discord.

*   **/filled** `price_per_gallon:float` `payment_amount:float` `payer:user(optional)`: Records gas fill-up, payment, and updates car cost per mile. Prompts for car selection. The payer can optionally be chosen if someone else paid.
    *   `price_per_gallon`: The price per gallon.
    *   `payment_amount`: The total amount paid for the fill-up.
    *   `payer`: (Optional) Mention the user who paid for the fill.
*   **/drove** `distance:str`: Records the miles driven by a user, prompts for car selection and near empty status.
    *  `distance`: The distance driven in miles.
*   **/balance**: Shows your current balance (how much you owe or are owed) - *ephemeral, only visible to you*.
*   **/allbalances**: Shows balances of all users, car cost per mile, and car near empty status.
*   **/car_usage**: Shows car usage data, including total miles driven.
*   **/settle**: Resets everyone's balance to zero.
*   **/help**: Displays this help message.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](LICENSE)

## Support

If you encounter any issues or have questions, please create an issue in this repository.
