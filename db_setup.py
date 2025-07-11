# db_setup.py (unchanged from previous)
import sqlite3
import pandas as pd

def init_db():
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            date DATE NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT CHECK(direction IN ('BUY', 'SELL')) NOT NULL,
            price REAL NOT NULL,
            shares REAL NOT NULL,
            fees REAL NOT NULL,
            position_size REAL NOT NULL
        )
    ''')

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

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully")
    import_data("Stock_Assets_tracking_logs.csv")
