# === Changes stop_loss_orders ===
# 3 calls made to client
def trailingStopLoss(sym, close):

    # Get the corresponding dict in symbol_dict
    d = symbol_dict.get(sym)
    original_price = float(d.get("original_price"))

    # If the current close price is greater than the original price, change the stop loss
    if close > original_price:

        # Gets the orderId of open orders, also gets the last stop price
        # Will only return 1 element, if you have 1 stop loss opened
        # Necessary for cancelling
        # IDEA: Could be updated in userInfo, every time new stop loss is made
        openOrder = client.get_open_orders(symbol=sym)  # 1

        # If there is no open order, do nothing (could be replaced by making a stop-loss)
        if not openOrder:
            return

        # If the openOrder is not a stop loss
        if openOrder[0]["type"] != "STOP_LOSS_LIMIT":
            return

        # Get the info of the old order, which needs to be cancelled
        # Oldest order will be the latest openOrder
        current_stop = float(openOrder[0]["stopPrice"])
        current_stop_id = openOrder[0]["orderId"]

        # Calculate the old stop percentage
        # Will be 1 + (95 - 100) / 100 = 0.95
        original_stop_price = symbol_dict[sym].get("original_stop_price")
        stop_percentage = 1 + (original_stop_price - original_price) / original_price

        # Set a stop loss at stopPercentage below the current price
        # Round it, otherwise it might not be allowed to use
        tick_precision = d.get("tick_precision")
        new_stop = round(close * stop_percentage, tick_precision)

        d["new_stop"] = new_stop

        # Update dict with current_stop and new_stop
        symbol_dict[sym] = d

        # If new stop price is higher than the old one, cancel old stop loss
        if new_stop > current_stop:
            # Cancel old stop loss order, needs that order id
            # For some reason this sometimes doesn't work and gives error:
            # binance.exceptions.BinanceAPIException: APIError(code=-2011): Unknown order sent.
            try:
                client.cancel_order(symbol=sym, orderId=current_stop_id)  # 2
            except Exception as e:
                print("Error cancelling old order:")
                print(e)
                # If order cant be cancelled, return
                return

        # If new stop would be lower than the old one, exit function here
        else:
            return

        # If no stop-loss exists or new stop is higer than old one, make new stop loss order
        # Limit price is the stop price but 1% smaller
        limit_price = round(new_stop * 0.99, tick_precision)

        # Convert to string, keeping it as a float will result in errors
        limit_price = f"{np.format_float_positional(limit_price)}"
        new_stop = f"{np.format_float_positional(new_stop)}"

        # Remove "." in case of converting number like 1.0, which will result in 1.
        if limit_price[-1] == ".":
            limit_price = limit_price[:-1]

        if new_stop[-1] == ".":
            new_stop = new_stop[:-1]

        start_quantity = d.get("quantity")
        step_precision = d.get("step_precision")

        # Try placing a stop loss order
        for x in range(0, 10):  # Max 10 times
            try:
                # start_quantity = start_quantity * 0.995
                quant = round_down((start_quantity * (0.995 ** x)), step_precision)
                client.create_order(
                    symbol=sym,
                    side="SELL",
                    type="STOP_LOSS_LIMIT",
                    quantity=quant,
                    stopPrice=new_stop,
                    price=limit_price,
                    timeInForce="GTC",
                )  # 3

                msg = " ".join(
                    [
                        "STOP_LOSS_LIMIT",
                        sym,
                        "$" + str(close),
                        str(new_stop),
                        str(limit_price),
                        "stop %",
                        str(stop_percentage),
                    ]
                )
                print(msg)
                break

            except binance.exceptions.BinanceAPIException as e:
                # Try again with lower quantity
                if (
                    e.message
                    == "Account has insufficient balance for requested action."
                ):
                    print("Retrying with lower quantity, times tried = " + str(x))
                    pass

                # Maybe undo the latest cancelled order after it fails for 10th time
                else:
                    msg = " ".join(
                        [
                            "Error at create_order, Tried:",
                            "STOP_LOSS_LIMIT",
                            sym,
                            "close=" + str(close),
                            "quantity=",
                            str(quant),
                            "stopPrice=",
                            str(new_stop),
                            "price=",
                            str(limit_price),
                            "stop %",
                            str(stop_percentage),
                        ]
                    )
                    print(msg)
                    print(e.message)


# https://github.com/StephanAkkerman/binance-trailing-stop-loss/tree/main/src