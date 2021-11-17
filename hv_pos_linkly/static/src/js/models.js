odoo.define('hv_pos_linkly.models', function (require) {
    var models = require('point_of_sale.models');
    var PaymentLinkly = require('hv_pos_linkly.payment');

    models.register_payment_method('linkly', PaymentLinkly);
    models.load_fields('pos.payment.method', 'linkly_terminal');

    var _super_paymentline = models.Paymentline.prototype;
    models.Paymentline = models.Paymentline.extend({
        initialize: function(attributes, options) {
            this.linkly_status = ""
            this.linkly_payment_id = 0
            this.linkly_payment_done = true
            this.can_be_reversed = false;
            _super_paymentline.initialize.apply(this,arguments);

        },
        init_from_JSON: function (json) {
            _super_paymentline.init_from_JSON.apply(this, arguments);
            this.linkly_status = json.linkly_status
            this.linkly_payment_id = json.linkly_payment_id
            this.linkly_payment_done = json.linkly_payment_done
            this.can_be_reversed = json.can_be_reversed
        },
        export_as_JSON: function () {
            const json = _super_paymentline.export_as_JSON.apply(this, arguments);
            json.linkly_status = this.linkly_status
            json.linkly_payment_id = this.linkly_payment_id
            json.linkly_payment_done = this.linkly_payment_done
            json.can_be_reversed = this.can_be_reversed
            return json;
        },
    });
});

odoo.define('hv_pos_linkly.LinklyPaymentStatus', function (require) {
    'use strict';

    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const { useListener } = require('web.custom_hooks');
    const Registries = require('point_of_sale.Registries');

    const LinklyPaymentStatus = (PaymentScreen) =>
        class extends PaymentScreen {
            constructor() {
                super(...arguments);
                useListener('send-payment-status', this._sendPaymentStatus);
            }

            async _sendPaymentStatus({ detail: line }) {
                const payment_terminal = line.payment_method.payment_terminal;
                line.set_payment_status('waiting');

                const isPaymentStatus = await payment_terminal.send_payment_status(line.cid);
                if (isPaymentStatus) {
                    line.set_payment_status('done');
                } else {
                    line.set_payment_status('retry');
                }
            }

            async _sendPaymentRequest({ detail: line }) {
                // Other payment lines can not be reversed anymore
                // this.paymentLines.forEach(function (line) {
                //     line.can_be_reversed = false;
                // });
    
                const payment_terminal = line.payment_method.payment_terminal;
                line.set_payment_status('waiting');
    
                const isPaymentSuccessful = await payment_terminal.send_payment_request(line.cid);
                if (isPaymentSuccessful) {
                    line.can_be_reversed = true;
                    line.set_payment_status('done');
                } else {
                    line.set_payment_status('retry');
                }
            }

            async _sendPaymentReverse({ detail: line }) {
                const payment_terminal = line.payment_method.payment_terminal;
                line.set_payment_status('reversing');
    
                const isReversalSuccessful = await payment_terminal.send_payment_reversal(line.cid);
                if (isReversalSuccessful) {
                    line.set_payment_status('pending');
                } else {
                    line.set_payment_status('done');
                }
            }

            deletePaymentLine(event) {
                const { cid } = event.detail;
                const line = this.paymentLines.find((line) => line.cid === cid);
                if (!line.linkly_payment_done && line.linkly_payment_id>0) {
                    line.set_payment_status('waitingCard');
                } else {
                    super.deletePaymentLine(event);
                }
            }

            selectPaymentLine(event) {
                const { cid } = event.detail;
                const line = this.paymentLines.find((line) => line.cid === cid);
                if (line!==undefined){
                    if ((!line.linkly_payment_done && line.linkly_payment_id>0) || this.currentOrder.electronic_payment_in_progress()) {
                    
                    } else {
                        super.selectPaymentLine(event);
                    } 
                }
            }
        };

    Registries.Component.extend(PaymentScreen, LinklyPaymentStatus);

    return LinklyPaymentStatus;
});