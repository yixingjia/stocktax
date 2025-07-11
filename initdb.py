# db_setup.py - Run this once to initialize the database
import sqlite3
import pandas as pd

def init_db():
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            date DATE NOT NULL,  -- Proper DATE type
            ticker TEXT NOT NULL,
            direction TEXT CHECK(direction IN ('BUY', 'SELL')) NOT NULL,
            price REAL NOT NULL,
            shares REAL NOT NULL,  -- Changed to REAL for fractional shares
            fees REAL NOT NULL,
            position_size REAL NOT NULL
        )
    ''')

    # Create realized gains table for FIFO calculations
    c.execute('''
        CREATE TABLE IF NOT EXISTS realized_gains (
            id INTEGER PRIMARY KEY,
            sell_id INTEGER NOT NULL,
            buy_id INTEGER NOT NULL,
            shares REAL NOT NULL,
            cost_basis REAL NOT NULL,
            FOREIGN KEY (sell_id) REFERENCES trades(id),
            FOREIGN KEY (buy_id) REFERENCES trades(id)
        )
    ''')
    conn.commit()
    conn.close()

def import_data(csv_path):
    df = pd.read_csv(csv_path)

    # Convert date to YYYY-MM-DD format for SQLite DATE type
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    conn = sqlite3.connect('stocks.db')
    df.rename(columns={
        'Date': 'date',
        'Ticker': 'ticker',
        'Direction': 'direction',
        'Price': 'price',
        'Shares': 'shares',
        'Fees': 'fees',
        'Position Size ($)': 'position_size'
    }).to_sql('trades', conn, if_exists='append', index=False)
    conn.close()

# Run this file separately to initialize DB
if __name__ == '__main__':
    init_db()
    # import_data('your_data.csv')  # Uncomment to import data
    print("Database initialized successfully")
