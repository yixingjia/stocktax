# app.py - Updated with batch import and visualization
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash
import plotly.express as px
import plotly.graph_objects as go
from io import StringIO
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# FIFO cost basis calculator
def calculate_fifo():
    conn = sqlite3.connect('stocks.db')
    conn.execute("DELETE FROM realized_gains")

    trades = pd.read_sql("""
        SELECT id, date, ticker, direction, price, shares, fees, position_size
        FROM trades
        ORDER BY date, id
    """, conn)

    for ticker in trades['ticker'].unique():
        ticker_trades = trades[trades['ticker'] == ticker].copy()
        buy_queue = []

        for _, trade in ticker_trades.iterrows():
            if trade['direction'] == 'BUY':
                cost_basis = (-trade['position_size']) / trade['shares']
                buy_queue.append({
                    'id': trade['id'],
                    'date': trade['date'],
                    'shares': trade['shares'],
                    'cost_basis': cost_basis
                })
            else:
                shares_to_sell = trade['shares']
                sell_id = trade['id']

                while shares_to_sell > 0 and buy_queue:
                    buy_lot = buy_queue[0]
                    shares_used = min(shares_to_sell, buy_lot['shares'])

                    conn.execute("""
                        INSERT INTO realized_gains (sell_id, buy_id, shares, cost_basis)
                        VALUES (?, ?, ?, ?)
                    """, (sell_id, buy_lot['id'], shares_used, buy_lot['cost_basis']))

                    buy_lot['shares'] -= shares_used
                    shares_to_sell -= shares_used

                    if buy_lot['shares'] <= 0.0001:
                        buy_queue.pop(0)

    conn.commit()
    conn.close()

def get_yearly_gains():
    conn = sqlite3.connect('stocks.db')
    gains = pd.read_sql("""
        SELECT
            strftime('%Y', t_sell.date) AS year,
            SUM(t_sell.price * rg.shares) AS proceeds,
            SUM(rg.cost_basis * rg.shares) AS cost_basis,
            SUM(t_sell.price * rg.shares - rg.cost_basis * rg.shares) AS realized_gain
        FROM realized_gains rg
        JOIN trades t_sell ON rg.sell_id = t_sell.id
        GROUP BY year
        ORDER BY year DESC
    """, conn)
    conn.close()
    return gains

def add_trade_record(form_data):
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()

    price = float(form_data['price'])
    shares = float(form_data['shares'])
    fees = float(form_data['fees'])

    if form_data['direction'] == 'BUY':
        position_size = -(price * shares) - fees
    else:
        position_size = (price * shares) - fees

    c.execute("""
        INSERT INTO trades (date, ticker, direction, price, shares, fees, position_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        form_data['date'],
        form_data['ticker'],
        form_data['direction'],
        price,
        shares,
        fees,
        position_size
    ))

    new_trade_id = c.lastrowid
    conn.commit()

    if form_data['direction'] == 'SELL':
        calculate_fifo()

    conn.close()
    return new_trade_id

def batch_import(csv_file):
    try:
        # Read CSV content
        content = csv_file.read().decode('utf-8')
        df = pd.read_csv(StringIO(content))

        # Validate columns
        required_columns = ['Date', 'Ticker', 'Direction', 'Price', 'Shares', 'Fees', 'Position Size ($)']
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            return False, f"Missing columns: {', '.join(missing)}"

        # Clean and prepare data
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

        # Recalculate FIFO for all sells
        calculate_fifo()

        conn.close()
        return True, f"Successfully imported {len(df)} records"
    except Exception as e:
        return False, f"Import error: {str(e)}"

# Flask routes
@app.route('/')
def dashboard():
    conn = sqlite3.connect('stocks.db')
    trades = pd.read_sql("SELECT * FROM trades ORDER BY date DESC", conn)
    conn.close()
    return render_template('dashboard.html', trades=trades.to_dict('records'))

@app.route('/add-trade', methods=['GET', 'POST'])
def add_trade():
    if request.method == 'POST':
        # Check if this is a batch import
        if 'csv_file' in request.files:
            file = request.files['csv_file']
            if file.filename != '':
                success, message = batch_import(file)
                if success:
                    flash(message, 'success')
                else:
                    flash(message, 'error')
                return redirect(url_for('add_trade'))

        # Handle single trade form
        try:
            required_fields = ['date', 'ticker', 'direction', 'price', 'shares', 'fees']
            if not all(field in request.form for field in required_fields):
                flash('All fields are required', 'error')
                return redirect(url_for('add_trade'))

            add_trade_record(request.form)
            flash('Trade added successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Error adding trade: {str(e)}', 'error')
            return redirect(url_for('add_trade'))

    return render_template('add_trade.html')

@app.route('/tax-report')
def tax_report():
    # Ensure FIFO is calculated
    calculate_fifo()

    # Get yearly summary
    yearly_gains = get_yearly_gains()

    # Get detailed transactions with proper grouping
    conn = sqlite3.connect('stocks.db')

    # First get all sell transactions
    sells = pd.read_sql("""
        SELECT
            t_sell.id AS sell_id,
            t_sell.date AS sell_date,
            t_sell.ticker,
            t_sell.price AS sell_price,
            t_sell.shares AS sell_shares
        FROM trades t_sell
        WHERE direction = 'SELL'
        ORDER BY sell_date DESC
    """, conn)

    # Then get matched buy details for each sell
    details = {}
    for _, sell in sells.iterrows():
        matches = pd.read_sql("""
            SELECT
                rg.shares AS matched_shares,
                t_buy.date AS buy_date,
                t_buy.price AS buy_price,
                rg.cost_basis,
                (t_sell.price * rg.shares) AS proceeds,
                (rg.cost_basis * rg.shares) AS cost,
                (t_sell.price * rg.shares - rg.cost_basis * rg.shares) AS gain
            FROM realized_gains rg
            JOIN trades t_sell ON rg.sell_id = t_sell.id
            JOIN trades t_buy ON rg.buy_id = t_buy.id
            WHERE rg.sell_id = ?
        """, conn, params=(sell['sell_id'],))

        details[sell['sell_id']] = {
            'sell_info': sell,
            'matches': matches.to_dict('records')
        }

    conn.close()

    return render_template('tax_report.html',
                           yearly=yearly_gains.to_dict('records'),
                           details=details)

@app.route('/visualize', methods=['GET', 'POST'])
def visualize():
    # Get unique tickers
    conn = sqlite3.connect('stocks.db')
    tickers = pd.read_sql("SELECT DISTINCT ticker FROM trades ORDER BY ticker", conn)['ticker'].tolist()

    # Get min/max dates
    date_range = pd.read_sql("SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM trades", conn)
    min_date = date_range['min_date'][0] or (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    max_date = date_range['max_date'][0] or datetime.now().strftime('%Y-%m-%d')
    conn.close()

    # Default values
    selected_ticker = request.form.get('ticker', tickers[0] if tickers else '')
    start_date = request.form.get('start_date', min_date)
    end_date = request.form.get('end_date', max_date)
    plot_html = None

    if request.method == 'POST' and selected_ticker:
        # Fetch data for selected ticker and date range
        conn = sqlite3.connect('stocks.db')
        query = """
            SELECT id, date, ticker, direction, price, shares, fees, position_size
            FROM trades
            WHERE ticker = ? AND date BETWEEN ? AND ?
            ORDER BY date
        """
        trades = pd.read_sql(query, conn, params=(selected_ticker, start_date, end_date))
        conn.close()

        if not trades.empty:
            # Create Plotly visualization with clean hover information
            fig = px.scatter(
                trades,
                x='date',
                y='price',
                color='direction',
                color_discrete_map={'BUY': 'green', 'SELL': 'red'},
                size=[10] * len(trades),  # Constant size for all markers
                hover_data=['shares', 'fees', 'position_size', 'direction'],
                title=f"{selected_ticker} Trading Activity"
            )

            # Customize hover template
            fig.update_traces(
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>"  # Direction
                    "Date: %{x}<br>"
                    "Price: $%{y:.4f}<br>"
                    "Shares: %{customdata[0]:.4f}<br>"
                    "Fees: $%{customdata[1]:.2f}<br>"
                    "Value: $%{customdata[2]:.2f}"
                )
            )

            # Add connecting line
            fig.add_trace(go.Scatter(
                x=trades['date'],
                y=trades['price'],
                mode='lines+markers',
                name='Price Trend',
                line=dict(color='royalblue', width=2),
                hoverinfo='skip'  # Skip hover for the line
            ))

            # Customize layout
            fig.update_layout(
                xaxis_title='Date',
                yaxis_title='Price per Share ($)',
                hovermode='closest',
                showlegend=True,
                template='plotly_white',
                legend=dict(
                    title_text='Direction',
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            plot_html = fig.to_html(full_html=False)

    return render_template('visualize.html',
                           tickers=tickers,
                           min_date=min_date,
                           max_date=max_date,
                           selected_ticker=selected_ticker,
                           start_date=start_date,
                           end_date=end_date,
                           plot_html=plot_html)

if __name__ == '__main__':
    # Create database if not exists
    if not os.path.exists('stocks.db'):
        conn = sqlite3.connect('stocks.db')
        conn.execute('''
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
        conn.execute('''
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
        conn.close()

    app.run(debug=True)
