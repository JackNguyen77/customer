
odoo.define('hv_pos_linkly.payment', function (require) {
    "use strict";

    var core = require('web.core');
    var rpc = require('web.rpc');
    var PaymentInterface = require('point_of_sale.PaymentInterface');
    const { Gui } = require('point_of_sale.Gui');

    var _t = core._t;

    var PaymentLinkly = PaymentInterface.extend({
        send_payment_reversal:function (cid) {
            this._super.apply(this, arguments);
            this._reset_state();
            return this._linkly_refund();
        },
        send_payment_request: function (cid) {
            this._super.apply(this, arguments);
            this._reset_state();
            return this._linkly_pay();
        },
        send_payment_status: function (cid) {
            this._reset_state();
            return this._linkly_status();
        },
        send_payment_cancel: function (order, cid) {
            this._super.apply(this, arguments);
            // set only if we are polling
            this._reset_state();
            return this._linkly_cancel();
        },
        close: function () {
            this._super.apply(this, arguments);
        },

        // private methods
        _reset_state: function () {
            this.was_cancelled = false;
            clearTimeout(this.polling);
        },

        _handle_odoo_connection_failure: function (data) {
            // handle timeout
            var line = this.pos.get_order().selected_paymentline;
            if (line) {
                line.set_payment_status('retry');
            }
            try {
                data.message.message = "Linkly Error:"
                data.message.data.debug = data.message.data.message
                data.message.data.message = ""
            } catch { }

            // this._show_error(_t('Could not connect to the Odoo server, please check your internet connection and try again.'));

            return Promise.reject(data); // prevent subsequent onFullFilled's from being called
        },

        _call_linkly_payment: function (data, operation) {
            return rpc.query({
                model: 'pos.payment.method',
                method: 'pos_linkly_payment',
                args: [[this.payment_method.id], data, operation],
            }, {
                timeout: 20000,
                shadow: true,
            }).catch(this._handle_odoo_connection_failure.bind(this));
        },

        _call_linkly_payment_cancel: function (line) {
            return rpc.query({
                model: 'pos.payment.method',
                method: 'pos_linkly_payment_cancel',
                args: [[this.payment_method.id], line.linkly_payment_id],
            }, {
                timeout: 20000,
                shadow: true,
            }).catch(this._handle_odoo_connection_failure.bind(this));
        },

        _call_linkly_payment_status: function (line) {
            return rpc.query({
                model: 'pos.payment.method',
                method: 'pos_linkly_payment_status',
                args: [[this.payment_method.id], line.linkly_payment_id],
            }, {
                timeout: 20000,
                shadow: true,
            }).catch(this._handle_odoo_connection_failure.bind(this));
        },

        _linkly_get_sale_id: function () {
            var config = this.pos.config;
            return _.str.sprintf('%s (ID: %s)', config.display_name, config.id);
        },

        _linkly_pay_data: function () {
            var order = this.pos.get_order();
            var config = this.pos.config;
            var line = order.selected_paymentline;
            var data = {
                'SaleID': this._linkly_get_sale_id(config),
                'TransactionID': order.uid,
                'Currency': this.pos.currency.id,
                'RequestedAmount': line.amount,
            }
            return data;
        },

        _linkly_pay: function () {
            var self = this;

            if (this.pos.get_order().selected_paymentline.amount < 0) {
                this._show_error(_t('Cannot process transactions with negative amount.'));
                return Promise.resolve();
            }
            var data = this._linkly_pay_data();

            return this._call_linkly_payment(data).then(function (data) {
                return self._linkly_handle_response(data);
            });
        },
        _linkly_status: function () {
            var self = this;
            var order = this.pos.get_order();
            var line = order.selected_paymentline;

            return this._call_linkly_payment_status(line).then(function (data) {
                return self._linkly_handle_response(data);
            });
        },
        _linkly_refund: function () {
            return Promise.resolve(false);
            var self = this;
            var order = this.pos.get_order();
            var line = order.selected_paymentline;

            return this._call_linkly_payment_status(line).then(function (data) {
                return self._linkly_handle_response(data);
            });
        },
        _linkly_cancel: function (ignore_error) {
            var self = this;
            var order = this.pos.get_order();
            var line = order.selected_paymentline;

            return this._call_linkly_payment_cancel(line).then(function (data) {
                return self._linkly_handle_response(data);
            });
            self._show_error(_t('Cancelling the payment failed. Please cancel it manually on the payment terminal.'));
        },

        _convert_receipt_info: function (output_text) {
            return output_text.reduce(function (acc, entry) {
                var params = new URLSearchParams(entry.Text);

                if (params.get('name') && !params.get('value')) {
                    return acc + _.str.sprintf('<br/>%s', params.get('name'));
                } else if (params.get('name') && params.get('value')) {
                    return acc + _.str.sprintf('<br/>%s: %s', params.get('name'), params.get('value'));
                }

                return acc;
            }, '');
        },

        _poll_for_response: function (resolve, reject) {
            var self = this;
            if (this.was_cancelled) {
                resolve(false);
                return Promise.resolve();
            }
            var order = self.pos.get_order();
            var line = order.selected_paymentline;
            return rpc.query({
                model: 'pos.payment.method',
                method: 'get_latest_linkly_status',
                args: [[this.payment_method.id], line.linkly_payment_id],
            }, {
                timeout: 20000,
                shadow: true,
            }).catch(function (data) {
                reject();
                return self._handle_odoo_connection_failure(data);
            }).then(function (response) {
                if (response.status == 1) {
                    var config = self.pos.config;
                    var payment_response = response.result;
                    var payment_result = response.result;

                    // var cashier_receipt = payment_response.PaymentReceipt.find(function (receipt) {
                    //     return receipt.DocumentQualifier == 'CashierReceipt';
                    // });

                    // if (cashier_receipt) {
                    //     line.set_cashier_receipt(self._convert_receipt_info(cashier_receipt.OutputContent.OutputText));
                    // }

                    // var customer_receipt = payment_response.PaymentReceipt.find(function (receipt) {
                    //     return receipt.DocumentQualifier == 'CustomerReceipt';
                    // });

                    // if (customer_receipt) {
                    //     line.set_receipt_info(self._convert_receipt_info(customer_receipt.OutputContent.OutputText));
                    // }

                    // var tip_amount = payment_result.AmountsResp.TipAmount;
                    // if (config.linkly_ask_customer_for_tip && tip_amount > 0) {
                    //     order.set_tip(tip_amount);
                    //     line.set_amount(payment_result.AmountsResp.AuthorizedAmount);
                    // }
                    line.name = self.payment_method.name
                    line.transaction_id = response.transaction_id;
                    line.card_type = response.card_type;
                    line.cardholder_name = response.cardholder_name;
                    line.linkly_payment_done = true
                    line.supports_reversals = true;
                    resolve(true);
                } else if (response.status == 0) {
                    line.linkly_payment_done = false
                    line.linkly_status = response.result;
                    line.set_payment_status('waitingCard');
                    // resolve(false);
                } else {
                    var message = response.result;
                    line.linkly_payment_done = true
                    self._show_error(_.str.sprintf(_t('Message from Linkly: %s'), message));
                    line.set_payment_status('retry');
                    reject();
                }
            });
        },

        _linkly_handle_response: function (response) {
            var self = this;
            var line = this.pos.get_order().selected_paymentline;
            if (response.status != 200) {
                if (typeof(response.result)=='string'){
                    this._show_error(_t(response.result));
                }else{
                    this._show_error(_t('Authentication failed. Please Pair PIN Pad.'));
                }
                line.linkly_payment_done = true
                return Promise.resolve(false);
            } else {
                line.linkly_payment_id = response.linkly_payment_id
                line.linkly_payment_done = false
                line.linkly_status = "Processing..."
                line.set_payment_status('waitingCard');
                var self = this;
                var res = new Promise(function (resolve, reject) {
                    // clear previous intervals just in case, otherwise
                    // it'll run forever
                    clearTimeout(self.polling);

                    self.polling = setInterval(function () {
                        self._poll_for_response(resolve, reject);
                    }, 3000);
                });

                // make sure to stop polling when we're done
                res.finally(function () {
                    self._reset_state();
                });

                return res;
            }
        },

        _show_error: function (msg, title) {
            if (!title) {
                title = _t('Linkly Error');
            }
            Gui.showPopup('ErrorPopup', {
                'title': title,
                'body': msg,
            });
        },
    });

    return PaymentLinkly;
});
