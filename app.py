
import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required, lookup, usd
import re

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure database
db = SQL("sqlite:///finance.db")

@app.after_request
def after_request(response):
    """No caching"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get user's stocks and shares from transactions
    portfolio = db.execute("""
        SELECT symbol, SUM(shares) as total_shares
        FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
        HAVING total_shares > 0
    """, session["user_id"])

    # Get current price for each stock and calculate total values
    grand_total = 0
    for stock in portfolio:
        quote = lookup(stock["symbol"])
        stock["name"] = quote["name"]
        stock["price"] = quote["price"]
        stock["total"] = stock["price"] * stock["total_shares"]
        grand_total += stock["total"]

    # Get user's current cash balance
    cash = db.execute("SELECT cash FROM users WHERE id = ?",
                     session["user_id"])[0]["cash"]
    grand_total += cash

    return render_template("index.html",
                         portfolio=portfolio,
                         cash=cash,
                         grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        # Validate symbol
        if not symbol:
            return apology("must provide symbol", 400)

        # Validate shares
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("must provide positive number of shares", 400)

        # Convert shares to integer
        shares = int(shares)

        # Look up stock
        quote = lookup(symbol)
        if quote is None:
            return apology("invalid symbol", 400)

        # Calculate total cost
        price = quote["price"]
        total_cost = price * shares

        # Get user's cash balance
        rows = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        cash = rows[0]["cash"]

        # Check if user can afford the purchase
        if cash < total_cost:
            return apology("can't afford", 400)

        # Update user's cash
        db.execute("UPDATE users SET cash = ? WHERE id = ?",
                  cash - total_cost, session["user_id"])

        # Record the transaction
        db.execute("""
                   INSERT INTO transactions
                     (user_id, symbol, shares, price, type)
                     VALUES (?, ?, ?, ?, ?)
                   """, session["user_id"], symbol.upper(), shares, price, "buy")

        # Redirect to home page
        flash(f"Bought {shares} shares of {symbol.upper()} for ${total_cost:,.2f}")
        return redirect("/")

    # GET request
    else:
        return render_template("buy.html")



@app.route("/history")
@login_required
def history():
    """Show history"""
    transactions = db.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY transacted DESC
    """, session["user_id"])
    return render_template("history.html", transactions=transactions)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    session.clear()
    if request.method == "POST":
        if not request.form.get("username"):
            return apology("Must provide username", 403)
        elif not request.form.get("password"):
            return apology("Must provide password", 403)

        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("Invalid username/password", 403)

        session["user_id"] = rows[0]["id"]
        return redirect("/")
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out"""
    session.clear()
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")

        if not symbol:
            return apology("missing symbol", 400)

        stock = lookup(symbol)
        if not stock:
            return apology("invalid symbol", 400)

        return render_template("quoted.html", stock=stock)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # When form is submitted via POST
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure password confirmation was submitted
        elif not request.form.get("confirmation"):
            return apology("must provide password confirmation", 400)

        # Ensure passwords match
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords must match", 400)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?",
                         request.form.get("username"))

        # Check if username already exists
        if len(rows) > 0:
            return apology("username already exists", 400)  # This line is crucial!

        # Add new user to database
        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)",
                  request.form.get("username"),
                  generate_password_hash(request.form.get("password")))

        # Query database for newly inserted user
        rows = db.execute("SELECT * FROM users WHERE username = ?",
                         request.form.get("username"))

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares"""
    if request.method == "GET":
        stocks = db.execute("""
            SELECT symbol FROM transactions
            WHERE user_id = ?
            GROUP BY symbol
            HAVING SUM(shares) > 0
        """, session["user_id"])
        return render_template("sell.html", stocks=stocks)
    else:
        symbol = request.form.get("symbol").upper()
        try:
            shares = int(request.form.get("shares"))
        except:
            return apology("Invalid shares", 400)

        if not symbol:
            return apology("Missing symbol", 400)
        if shares < 1:
            return apology("Invalid shares", 400)

        available = db.execute("""
            SELECT SUM(shares) as total
            FROM transactions
            WHERE user_id = ? AND symbol = ?
        """, session["user_id"], symbol)[0]["total"]

        if not available or shares > available:
            return apology("Not enough shares", 400)

        stock = lookup(symbol)
        value = stock["price"] * shares

        db.execute("""
            INSERT INTO transactions
            (user_id, symbol, shares, price, type)
            VALUES (?, ?, ?, ?, 'sell')
        """, session["user_id"], symbol, -shares, stock["price"])

        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", value, session["user_id"])

        flash("Sold!")
        return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)