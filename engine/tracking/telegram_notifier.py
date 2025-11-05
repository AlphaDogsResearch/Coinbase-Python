"""
Telegram Notifier with Bot Command Support.

Event-driven notification system for orders, signals, and account updates.
Implements listener interfaces to decouple from order management system.
"""

import logging
import asyncio
import threading
from datetime import datetime
from queue import Queue, Empty
from typing import Optional, List

import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from common.interface_order import OrderEvent, OrderStatus, Order, Side, OrderType
from engine.tracking.order_history import OrderHistory


class TelegramNotifier:
    """
    Telegram notification system with bot command support.

    Listens to order events, signals, and account updates to send
    real-time notifications. Supports bot commands for querying history.
    """

    def __init__(
        self, api_key: str, user_id: str, exchange_env: str, account=None, position_manager=None
    ):
        """
        Initialize Telegram notifier.

        Args:
            api_key: Telegram bot API key
            user_id: Telegram user ID to send messages to
            exchange_env: Environment name (testnet/production)
            account: Account instance for balance/margin info
            position_manager: PositionManager instance for position info
        """
        self.api_key = api_key
        self.user_id = user_id
        self.exchange_env = exchange_env.upper() if exchange_env else "TESTNET"
        self.account = account
        self.position_manager = position_manager

        # Enable flag - if Telegram fails to initialize, disable all operations
        self.enabled = False

        # Order and signal history (always works, even if Telegram is disabled)
        self.history = OrderHistory(max_orders=50, max_signals=100)

        # Message queue for non-blocking async sending
        self.message_queue: Queue[str] = Queue(maxsize=1000)
        self.sender_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()

        # Telegram bot
        try:
            self.bot = telegram.Bot(token=self.api_key)
            self.enabled = True
            logging.info("✅ Telegram bot initialized successfully")
        except Exception as e:
            logging.error(f"❌ Failed to initialize Telegram bot: {e}")
            logging.warning("⚠️ Telegram notifications DISABLED - trading will continue normally")
            self.bot = None

        # Bot application for commands
        self.application = None
        self.bot_thread = None

    def send_message(self, message: str) -> None:
        """
        Queue a message to be sent (non-blocking).

        Args:
            message: Message text to send
        """
        if not self.enabled:
            # Silently skip if Telegram is disabled
            return

        try:
            # Try to add to queue without blocking
            self.message_queue.put_nowait(message)
        except Exception as e:
            # Queue is full or other error - log but don't fail
            logging.warning(f"Failed to queue Telegram message (queue full or error): {e}")

    def _message_sender_worker(self) -> None:
        """
        Background worker thread that sends messages from the queue.

        This ensures message sending never blocks the main trading logic.
        """
        loop = None
        try:
            # Create a dedicated event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while not self.shutdown_event.is_set():
                try:
                    # Wait for message with timeout to allow checking shutdown flag
                    message = self.message_queue.get(timeout=1.0)

                    if not self.enabled or not self.bot:
                        continue

                    # Send message with timeout
                    try:
                        # Send with timeout (10 seconds max)
                        async def send_with_timeout():
                            await asyncio.wait_for(
                                self.bot.send_message(
                                    chat_id=self.user_id, text=message, parse_mode="HTML"
                                ),
                                timeout=10.0,
                            )

                        loop.run_until_complete(send_with_timeout())

                    except asyncio.TimeoutError:
                        logging.warning("⚠️ Telegram message send timeout (10s) - skipping")
                    except Exception as e:
                        logging.error(f"❌ Error sending Telegram message: {e}")
                        # If we get multiple consecutive errors, consider disabling

                except Empty:
                    # No message in queue, continue waiting
                    continue
                except Exception as e:
                    logging.error(
                        f"❌ Unexpected error in Telegram sender thread: {e}", exc_info=True
                    )

        except Exception as e:
            logging.error(f"❌ Error in message sender worker: {e}", exc_info=True)
        finally:
            # Clean up the event loop
            if loop and not loop.is_closed():
                try:
                    # Cancel any pending tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        # Wait for tasks to be cancelled
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()
                except Exception as e:
                    logging.debug(f"Error closing event loop: {e}")

    def on_order_submitted(self, order: Order) -> None:
        """
        Listener for order submission events.

        Args:
            order: Submitted order
        """
        try:
            # Store in history
            order_data = {
                "order_id": order.order_id,
                "strategy_id": order.strategy_id,
                "symbol": order.symbol,
                "side": order.side.name,
                "quantity": order.quantity,
                "price": order.price,
                "status": "SUBMITTED",
                "notional": order.quantity * order.price if order.price else None,
            }
            self.history.add_order(order_data)

            # Format and send notification
            message = self.format_order_submitted_message(order)
            self.send_message(message)
        except Exception as e:
            logging.error(f"Error in on_order_submitted: {e}", exc_info=True)

    def on_order_event(self, order_event: OrderEvent) -> None:
        """
        Listener for order status change events.

        Args:
            order_event: Order event with status update
        """
        try:
            status = order_event.status

            # Update history
            order_data = {
                "order_id": order_event.order_id,
                "symbol": order_event.contract_name,
                "side": order_event.side,
                "status": status.name,
                "filled_quantity": getattr(order_event, "last_filled_quantity", None),
                "filled_price": getattr(order_event, "last_filled_price", None),
                "timestamp": getattr(order_event, "last_filled_time", None),
            }
            self.history.add_order(order_data)

            # Send notifications for important status changes
            if status == OrderStatus.FILLED:
                message = self.format_order_filled_message(order_event)
                self.send_message(message)

            elif status == OrderStatus.CANCELED:
                message = self.format_order_canceled_message(order_event)
                self.send_message(message)

            elif status == OrderStatus.FAILED:
                message = self.format_order_failed_message(order_event)
                self.send_message(message)

        except Exception as e:
            logging.error(f"Error in on_order_event: {e}", exc_info=True)

    def on_margin_warning(self, message: str) -> None:
        """
        Listener for margin warning events from Account.

        Args:
            message: Warning message to send
        """
        try:
            # Add warning emoji if not already present
            if not message.startswith("⚠️") and not message.startswith("❗"):
                message = f"⚠️ {message}"

            self.send_message(message)
        except Exception as e:
            logging.error(f"Error in on_margin_warning: {e}", exc_info=True)

    def on_strategy_order_submitted(
        self,
        strategy_id: str,
        side: Side,
        order_type: OrderType,
        notional: float,
        price: float,
        symbol: str,
        tags: List[str],
    ) -> None:
        """
        Listener for strategy order submission events with detailed tag information.

        Args:
            strategy_id: Strategy identifier
            side: Order side (BUY/SELL)
            order_type: Order type (Market, Limit, StopMarket, etc.)
            notional: Order notional value
            price: Order price
            symbol: Trading symbol
            tags: List of order tags with metadata
        """
        try:
            # Compute derived fields
            quantity = notional / price if price and price > 0 else 0.0
            action = None
            try:
                tag_info = self._parse_order_tags(tags or [])
                action = tag_info.get("action")
            except Exception:
                action = None

            # Store in order history (for /orders)
            order_data = {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side.name,
                "order_type": order_type.name,
                "notional": notional,
                "price": price,
                "quantity": quantity,
                "status": "SUBMITTED",
                "tags": tags,
            }
            self.history.add_order(order_data)

            # Store in signal history (for /signals)
            signal_value = 0
            if action == "CLOSE":
                signal_value = 0
            else:
                signal_value = 1 if side == Side.BUY else -1

            signal_data = {
                "strategy_id": self._clean_strategy_name(strategy_id),
                "symbol": symbol,
                "signal": signal_value,
                "price": price,
                "quantity": quantity,
                "action": action or "ORDER",
                "order_type": order_type.name,
                "tags": tags,
            }
            self.history.add_signal(signal_data)

            # Format and send detailed notification
            message = self.format_strategy_order_submitted_message(
                strategy_id, side, order_type, notional, price, symbol, tags
            )
            self.send_message(message)
        except Exception as e:
            logging.error(f"Error in on_strategy_order_submitted: {e}", exc_info=True)

    def on_unrealized_pnl_update(self, unrealized_pnl: float) -> None:
        """Handle unrealized PnL updates."""
        try:
            # Only send notifications for significant PnL changes (avoid spam)
            if abs(unrealized_pnl) > 10.0:  # Only notify for PnL > $10
                message = self.format_unrealized_pnl_message(unrealized_pnl)
                self.send_message(message)
        except Exception as e:
            logging.error(f"Error in on_unrealized_pnl_update: {e}", exc_info=True)

    def on_realized_pnl_update(self, realized_pnl: float) -> None:
        """Handle realized PnL updates."""
        try:
            # Always notify for realized PnL (actual profits/losses)
            message = self.format_realized_pnl_message(realized_pnl)
            self.send_message(message)
        except Exception as e:
            logging.error(f"Error in on_realized_pnl_update: {e}", exc_info=True)

    def _clean_strategy_name(self, strategy_id: str) -> str:
        """
        Clean up strategy name for display.

        Removes 'NautilusAdapter(' prefix and closing ')' if present.
        Example: 'NautilusAdapter(SimpleOrderTestStrategy:ETHUSDT)' -> 'SimpleOrderTestStrategy:ETHUSDT'
        """
        if strategy_id.startswith("NautilusAdapter(") and strategy_id.endswith(")"):
            return strategy_id[16:-1]  # Remove 'NautilusAdapter(' and ')'
        return strategy_id

    # Removed unused _calculate_pnl helper to simplify notifier

    def format_order_submitted_message(self, order: Order) -> str:
        """Format order submission message."""
        notional = order.quantity * order.price if order.price else 0
        timestamp = datetime.fromtimestamp(order.timestamp / 1000).strftime("%H:%M:%S")

        message = f"📊 <b>ORDER SUBMITTED</b>\n"
        message += f"<b>{order.side.name}</b> {order.symbol}\n"
        message += f"Strategy: {self._clean_strategy_name(order.strategy_id)}\n"
        message += f"Quantity: {order.quantity:.4f}\n"
        message += f"Price: ${order.price:.2f}\n"
        message += f"Notional: ${notional:.2f}\n"
        message += f"Order ID: {order.order_id}\n"
        message += f"Time: {timestamp}"

        return message

    def format_order_filled_message(self, order_event: OrderEvent) -> str:
        """Format order filled message."""
        side = order_event.side
        filled_qty = float(order_event.last_filled_quantity)
        filled_price = float(order_event.last_filled_price)
        notional = filled_qty * filled_price

        # Check if this was originally a stop loss order
        is_stop_loss_triggered = order_event.order_type == OrderType.StopMarket

        if is_stop_loss_triggered:
            message = f"🛑 <b>STOP LOSS TRIGGERED</b>\n"
        else:
            message = f"✅ <b>ORDER FILLED</b>\n"

        message += f"<b>{side}</b> {order_event.contract_name} @ ${filled_price:.2f}\n"
        message += f"Quantity: {filled_qty:.4f} (${notional:.0f})\n"
        message += f"ID: {order_event.order_id}"

        return message

    def format_order_canceled_message(self, order_event: OrderEvent) -> str:
        """Format order canceled message."""
        message = f"❌ <b>ORDER CANCELED</b>\n"
        message += f"{order_event.contract_name}\n"
        message += f"ID: {order_event.order_id}"
        return message

    def format_order_failed_message(self, order_event: OrderEvent) -> str:
        """Format order failed message."""
        message = f"❌ <b>ORDER FAILED</b>\n"
        message += f"{order_event.contract_name}\n"
        message += f"ID: {order_event.order_id}"
        return message

    def format_strategy_order_submitted_message(
        self,
        strategy_id: str,
        side: Side,
        order_type: OrderType,
        notional: float,
        price: float,
        symbol: str,
        tags: List[str],
    ) -> str:
        """Format clear and simple strategy order submission message."""
        # Parse tags for rich information
        tag_info = self._parse_order_tags(tags)

        # Determine order type and action
        action = tag_info.get("action", "")
        is_entry = action == "ENTRY"
        is_stop_loss = action == "STOP_LOSS" or order_type == OrderType.StopMarket
        is_close = action == "CLOSE"

        # Calculate quantity
        quantity = notional / price if price > 0 else 0
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Clear, simple formatting
        if is_entry:
            # Entry orders - clear buy/sell indication
            direction = "BUY" if side == Side.BUY else "SELL"
            message = f"🚀 <b>ENTRY ORDER</b>\n"
            message += f"<b>{direction}</b> {symbol} @ ${price:.2f}\n"
        elif is_stop_loss:
            # Stop loss orders - clear stop indication
            direction = "BUY" if side == Side.BUY else "SELL"
            message = f"🛑 <b>STOP LOSS</b>\n"
            message += f"<b>{direction}</b> {symbol} @ ${price:.2f}\n"
        elif is_close:
            # Close orders - clear close indication
            direction = "BUY" if side == Side.BUY else "SELL"
            message = f"🔚 <b>CLOSE POSITION</b>\n"
            message += f"<b>{direction}</b> {symbol} @ ${price:.2f}\n"
        else:
            # Generic orders
            direction = "BUY" if side == Side.BUY else "SELL"
            message = f"📊 <b>ORDER</b>\n"
            message += f"<b>{direction}</b> {symbol} @ ${price:.2f}\n"

        # Add essential details
        message += f"Strategy: {self._clean_strategy_name(strategy_id)}\n"
        message += f"Quantity: {quantity:.4f} ({notional:.0f} USDT)\n"
        message += f"Type: {order_type.name}\n"
        message += f"Time: {timestamp}\n"

        # Add rationale if available
        if "rationale" in tag_info:
            message += f"Reason: {tag_info['rationale']}\n"

        # Add signal ID for correlation
        if "signal_id" in tag_info:
            message += f"ID: <code>{tag_info['signal_id'][:8]}</code>\n"

        # Environment
        message += f"Env: {self.exchange_env}"

        return message

    def format_unrealized_pnl_message(self, unrealized_pnl: float) -> str:
        """Format unrealized PnL update message."""
        if unrealized_pnl > 0:
            emoji = "📈"
            direction = "PROFIT"
        else:
            emoji = "📉"
            direction = "LOSS"

        message = f"{emoji} <b>UNREALIZED PnL</b>\n"
        message += f"<b>{direction}:</b> ${abs(unrealized_pnl):.2f}\n"
        message += f"Time: {datetime.now().strftime('%H:%M:%S')}\n"
        message += f"Env: {self.exchange_env}"

        return message

    def format_realized_pnl_message(self, realized_pnl: float) -> str:
        """Format realized PnL update message."""
        if realized_pnl > 0:
            emoji = "💰"
            direction = "PROFIT"
        else:
            emoji = "💸"
            direction = "LOSS"

        message = f"{emoji} <b>REALIZED PnL</b>\n"
        message += f"<b>{direction}:</b> ${abs(realized_pnl):.2f}\n"
        message += f"Time: {datetime.now().strftime('%H:%M:%S')}\n"
        message += f"Env: {self.exchange_env}"

        return message

    def _parse_order_tags(self, tags: List[str]) -> dict:
        """Parse order tags into a structured dictionary."""
        tag_info = {}

        for tag in tags:
            if "=" in tag:
                key, value = tag.split("=", 1)
                tag_info[key] = value
            else:
                # Handle tags without key=value format
                if tag in ["ENTRY", "STOP_LOSS", "CLOSE"]:
                    tag_info["action"] = tag
                elif tag in ["TP", "SL"]:
                    tag_info[tag.lower()] = "Yes"

        return tag_info

    def format_account_metrics(self) -> str:
        """Format current account metrics."""
        if not self.account:
            return "Account info not available"

        wallet_balance = self.account.wallet_balance
        margin_ratio = self.account.get_margin_ratio()
        maint_margin = self.account.maint_margin
        unrealized_pnl = self.account.unrealised_pnl

        message = f"💰 <b>Account Status</b>\n"
        message += f"Environment: <b>{self.exchange_env}</b>\n\n"
        message += f"Wallet Balance: ${wallet_balance:.2f}\n"
        message += f"Unrealized PnL: ${unrealized_pnl:.2f}\n"
        message += f"Maint Margin: ${maint_margin:.2f}\n"

        if margin_ratio is not None:
            message += f"Margin Ratio: {margin_ratio:.2%}\n"

        # Add position info if available
        if self.position_manager:
            positions = self.position_manager.positions
            if positions:
                message += f"\n<b>Open Positions:</b>\n"
                for symbol, position in positions.items():
                    if position.position_amount != 0:
                        message += f"{symbol}: {position.position_amount:.4f} @ ${position.entry_price:.2f}\n"

        return message

    # Bot command handlers
    async def cmd_help(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = (
            "<b>Available Commands:</b>\n\n"
            "/status - Show account status and positions\n"
            "/orders [count] - Show recent orders (default: 10)\n"
            "/signals [count] - Show recent signals (default: 10)\n"
            "/help - Show this help message"
        )
        await update.message.reply_text(help_text, parse_mode="HTML")

    async def cmd_status(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        message = self.format_account_metrics()
        await update.message.reply_text(message, parse_mode="HTML")

    async def cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /orders command."""
        try:
            count = 10
            if context.args and len(context.args) > 0:
                count = int(context.args[0])
                count = min(count, 50)  # Cap at 50

            orders = self.history.get_recent_orders(count)

            if not orders:
                await update.message.reply_text("No orders found.")
                return

            message = f"📊 <b>Recent Orders ({len(orders)}):</b>\n\n"

            for order in orders:
                timestamp = order.get("timestamp", datetime.now()).strftime("%H:%M:%S")
                side = order.get("side", "N/A")
                symbol = order.get("symbol", "N/A")
                qty = order.get("quantity", 0)
                price = order.get("price", 0)
                status = order.get("status", "N/A")
                order_id = order.get("order_id", "N/A")

                message += f"{timestamp} <b>{side}</b> {symbol}\n"
                message += f"Qty: {qty:.4f} @ ${price:.2f}\n"
                message += f"Status: {status} | ID: {order_id}\n\n"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logging.error(f"Error in cmd_orders: {e}", exc_info=True)
            await update.message.reply_text(f"Error retrieving orders: {str(e)}")

    async def cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /signals command."""
        try:
            count = 10
            if context.args and len(context.args) > 0:
                count = int(context.args[0])
                count = min(count, 100)  # Cap at 100

            signals = self.history.get_recent_signals(count)

            if not signals:
                await update.message.reply_text("No signals found.")
                return

            message = f"📈 <b>Recent Signals ({len(signals)}):</b>\n\n"

            for sig in signals:
                timestamp = sig.get("timestamp", datetime.now()).strftime("%H:%M:%S")
                strategy = sig.get("strategy_id", "N/A")
                signal = sig.get("signal", 0)
                symbol = sig.get("symbol", "N/A")
                price = sig.get("price", 0)
                quantity = sig.get("quantity", 0)
                action = sig.get("action", "")

                signal_emoji = "📈" if signal > 0 else "📉"
                signal_text = "LONG" if signal > 0 else "SHORT"

                if action == "CLOSE" or signal == 0:
                    message += f"{timestamp} 🔚 <b>CLOSE</b> {symbol}\n"
                elif action == "STOP_LOSS":
                    message += f"{timestamp} 🛑 <b>STOP LOSS</b> {symbol}\n"
                elif action == "ENTRY":
                    message += f"{timestamp} {signal_emoji} <b>{signal_text}</b> {symbol}\n"
                else:
                    message += f"{timestamp} {signal_emoji} <b>{signal_text}</b> {symbol}\n"

                message += f"Strategy: {strategy}\n"
                message += f"Qty: {quantity:.4f} @ ${price:.2f}\n\n"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logging.error(f"Error in cmd_signals: {e}", exc_info=True)
            await update.message.reply_text(f"Error retrieving signals: {str(e)}")

    def start_bot_listener(self) -> None:
        """Start the Telegram bot command listener and message sender threads."""
        if not self.enabled:
            return

        # Start message sender thread first
        try:
            self.sender_thread = threading.Thread(
                target=self._message_sender_worker, daemon=True, name="TelegramSender"
            )
            self.sender_thread.start()
        except Exception as e:
            logging.error(f"❌ Failed to start Telegram sender thread: {e}")
            self.enabled = False
            return

        # Start bot command listener thread
        def run_bot():
            """Run bot in separate thread with its own event loop."""
            loop = None
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Create application without signal handlers (not available in background threads)
                self.application = Application.builder().token(self.api_key).build()

                # Add command handlers
                self.application.add_handler(CommandHandler("help", self.cmd_help))
                self.application.add_handler(CommandHandler("start", self.cmd_help))
                self.application.add_handler(CommandHandler("status", self.cmd_status))
                self.application.add_handler(CommandHandler("orders", self.cmd_orders))
                self.application.add_handler(CommandHandler("signals", self.cmd_signals))

                # Run polling with periodic shutdown checks
                async def polling_loop():
                    try:
                        # Initialize and start the application
                        await self.application.initialize()
                        await self.application.start()

                        # Start polling once (only if not already running)
                        if not self.application.updater.running:
                            await self.application.updater.start_polling(
                                allowed_updates=Update.ALL_TYPES,
                                timeout=1.0,
                            )

                        # Wait for shutdown signal
                        while not self.shutdown_event.is_set():
                            await asyncio.sleep(0.1)  # Check shutdown every 100ms

                    except Exception as e:
                        logging.error(f"❌ Error in polling loop: {e}")
                    finally:
                        # Stop the application
                        try:
                            await self.application.stop()
                        except Exception as e:
                            logging.debug(f"Error stopping application: {e}")

                # Run the polling loop
                loop.run_until_complete(polling_loop())

            except Exception as e:
                logging.error(f"❌ Error in Telegram bot listener: {e}", exc_info=True)
                # Even if bot listener fails, keep sender thread running for notifications
            finally:
                # Clean up the event loop
                if loop and not loop.is_closed():
                    try:
                        # Cancel any pending tasks
                        pending = asyncio.all_tasks(loop)
                        if pending:
                            for task in pending:
                                task.cancel()
                            # Wait for tasks to be cancelled
                            loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                        loop.close()
                    except Exception as e:
                        logging.debug(f"Error closing bot event loop: {e}")

        # Start bot thread
        try:
            self.bot_thread = threading.Thread(target=run_bot, daemon=True, name="TelegramBot")
            self.bot_thread.start()
        except Exception as e:
            logging.error(f"❌ Failed to start Telegram bot thread: {e}")
            # Don't disable - sender thread can still work for notifications

    def stop_bot_listener(self) -> None:
        """Stop the Telegram bot listener and message sender threads."""
        logging.info("🛑 Stopping Telegram notifier...")

        # Signal shutdown first
        self.shutdown_event.set()

        # Stop message sender thread
        if self.sender_thread and self.sender_thread.is_alive():
            try:
                logging.info("🛑 Stopping Telegram sender thread...")
                self.sender_thread.join(timeout=3.0)
                if self.sender_thread.is_alive():
                    logging.warning("⚠️ Telegram sender thread did not stop gracefully")
                else:
                    logging.info("✅ Telegram sender thread stopped")
            except Exception as e:
                logging.error(f"❌ Error stopping sender thread: {e}")

        # Stop bot application
        if self.application:
            try:
                # Check if application is actually running before stopping
                if hasattr(self.application, "running") and self.application.running:
                    logging.info("🛑 Stopping Telegram bot command listener...")
                    # Use a new event loop for shutdown to avoid conflicts
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.application.stop())
                        loop.close()
                        logging.info("✅ Telegram bot stopped")
                    except Exception as e:
                        logging.warning(f"⚠️ Error stopping bot application: {e}")
                else:
                    logging.debug("Telegram bot application already stopped")
            except Exception as e:
                logging.warning(f"⚠️ Error stopping Telegram bot: {e}")

        # Wait for bot thread
        if self.bot_thread and self.bot_thread.is_alive():
            try:
                logging.info("🛑 Stopping Telegram bot thread...")
                self.bot_thread.join(timeout=1.0)  # Reduced timeout
                if self.bot_thread.is_alive():
                    logging.warning(
                        "⚠️ Telegram bot thread did not stop gracefully - forcing shutdown"
                    )
                    # Force stop by setting daemon thread (will be killed when main thread exits)
                    self.bot_thread.daemon = True
                    # Try to interrupt the thread if possible
                    try:
                        import ctypes

                        ctypes.pythonapi.PyThreadState_SetAsyncExc(
                            ctypes.c_long(self.bot_thread.ident), ctypes.py_object(SystemExit)
                        )
                    except Exception:
                        pass  # Ignore if we can't interrupt
                else:
                    logging.info("✅ Telegram bot thread stopped")
            except Exception as e:
                logging.error(f"❌ Error joining bot thread: {e}")

        # Clear the message queue to prevent any remaining messages
        try:
            while not self.message_queue.empty():
                self.message_queue.get_nowait()
        except Exception:
            pass

        logging.info("✅ Telegram notifier stopped")

    def is_enabled(self) -> bool:
        """
        Check if Telegram notifications are enabled and working.

        Returns:
            True if enabled, False otherwise
        """
        return self.enabled and self.bot is not None

    def get_status(self) -> dict:
        """
        Get status information about the Telegram notifier.

        Returns:
            Dictionary with status information
        """
        return {
            "enabled": self.enabled,
            "bot_initialized": self.bot is not None,
            "sender_thread_alive": self.sender_thread.is_alive() if self.sender_thread else False,
            "bot_thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "queue_size": self.message_queue.qsize(),
            "total_orders": self.history.get_order_count(),
            "total_signals": self.history.get_signal_count(),
        }
