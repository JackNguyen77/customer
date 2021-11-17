# coding: utf-8

import base64
import uuid
import pprint
import json, re
import hashlib
import logging
import requests
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime, timedelta

MAP_INVOICE_TYPE_PAYMENT_SIGN = {
    'out_invoice': 1,
    'in_refund': -1,
    'in_invoice': -1,
    'out_refund': 1,
}
_logger = logging.getLogger(__name__)
        
CURRENCY_CODE_MAPS = {
    "BHD": 3,
    "CVE": 0,
    "DJF": 0,
    "GNF": 0,
    "IDR": 0,
    "JOD": 3,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "PYG": 0,
    "RWF": 0,
    "TND": 3,
    "UGX": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
}
class Acquirerwarrior(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('linkly', 'Linkly')], ondelete={'linkly': 'set default'})

class Account_Journal(models.Model):
    _inherit = 'account.journal'

    linkly_time_out = fields.Integer(string='Time Out (s)', default=45)
    use_payment_terminal = fields.Selection([('none', 'None'), ('linkly', 'Linkly')], string='Use a Payment Terminal', help='Record payments with a terminal on this journal.')
    linkly_account = fields.Char(string='Linkly Username')
    linkly_api_password = fields.Char(string="Linkly Password", copy=False)
    linkly_paircode = fields.Char(string="Linkly Paircode",help='PairCode when PIN Paid connect to EFT cloud.', copy=False)
    linkly_secret = fields.Char(string="Linkly Secret", copy=False)
    linkly_token = fields.Char(string="Linkly Token", copy=False)
    linkly_token_expire = fields.Datetime(string="Linkly Token expire date", copy=False)
    linkly_test_mode = fields.Boolean(help='Run transactions in the test environment.', default="True")

    acquirer_id = fields.Many2one('payment.acquirer', string="Payment Acquirer")

    def raise_error(self, message):
        if self.env.context.get('call_from_pos', False):
            raise ValueError(message)
        else:
            raise ValidationError(message)

    def get_linkly_mode(self):
        if self.linkly_test_mode:
            return '0'
        else:
            return '1'

    def linkly_pair_pin_pad(self):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        headers = {
            'Content-Type': 'application/json',
            'livemode': self.get_linkly_mode()
        }
        data = {
            'username': self.linkly_account,
            'password': self.linkly_api_password,
            'pairCode': self.linkly_paircode,
            'Notification':{
                'Uri': '%s/linkly/notification/0/0' % (callback_url),
            }
        }
        tres = self.proxy_linkly_request('/pairing', headers, data)
        if tres['status'] == 200:
            self.linkly_secret = tres['result']['secret']
            self.linkly_token = ''
            self.linkly_token_expire = datetime.now()      
        elif tres['status'] == 606:  
            self.raise_error(_(tres['result']))
        else:
            self.raise_error(_("Cannot pair the Pin Pad."))

    def _linkly_get_token(self):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        if self.linkly_token_expire and datetime.now() < self.linkly_token_expire:
            return self.linkly_token

        if not self.linkly_secret:
            self.raise_error(_('Please paring a Pin Pad for this Linkly Journal!'))

        headers = {
            'Content-Type': 'application/json',
            'livemode': self.get_linkly_mode()
        }
        data = {
            "secret": self.linkly_secret,
            "posName": self.name,
            "posVersion": "1.0",
            "posId": str(uuid.uuid4()),
            "posVendorId": '%s - %s' % (self.env.company.name, self.env.user.id),
            'Notification':{
                'Uri': '%s/linkly/notification/0/0' % (callback_url),
            }
        }
        tres = self.proxy_linkly_request('/token', headers, data)
        if tres['status'] == 200:
            if 'token' in tres['result']:
                self.linkly_token = tres['result']['token']
                sec = int(tres['result']['expirySeconds']) - 1000
                self.linkly_token_expire = datetime.now() + timedelta(seconds=sec)
                self._cr.commit()
            return self.linkly_token
        elif tres['status'] == 606:  
            self.raise_error(_(tres['result']))
        else:
            self.raise_error(_("Cannot get the token. Please Pair PIN Pad."))

    def _linkly_payment(self, sessiondata):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        headers = {
            'Authorization': self._linkly_get_token(),
            'Content-Type': 'application/json',
            'sessionId': sessiondata['session'],
            'livemode': self.get_linkly_mode()
        }
        data = {
            'request': {
                'txnType': 'P',
                'amtPurchase': sessiondata['amtPurchase'],
                'txnRef': sessiondata['txnRef'],
            },
            'Notification':{
                'Uri': '%s/linkly/notification/%s/%s' % (callback_url, sessiondata['session'], sessiondata['linkly_payment_id']),
            }
        }
        return self.proxy_linkly_request('/payment', headers, data)

    def _linkly_refund(self, sessiondata):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        headers = {
            'Authorization': self._linkly_get_token(),
            'Content-Type': 'application/json',
            'sessionId': sessiondata['session'],
            'livemode': self.get_linkly_mode()
        }
        data = {
            'request': {
                "Merchant": "00",
                "TxnType": "R",
                'amtPurchase': sessiondata['amtPurchase'],
                'txnRef': sessiondata['txnRef'],
            },
            'Notification':{
                'Uri': '%s/linkly/notification/%s/%s' % (callback_url, sessiondata['session'], sessiondata['linkly_payment_id']),
            }
        }
        return self.proxy_linkly_request('/refund', headers, data)

    def _linkly_payment_cancel(self, sessiondata):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        headers = {
            'Authorization': self._linkly_get_token(),
            'Content-Type': 'application/json',
            'sessionId': sessiondata['session'],
            'livemode': self.get_linkly_mode()
        }
        data = {
            'request': {
                'key': '0'
            },            
            'Notification':{
                'Uri': '%s/linkly/notification/%s/%s' % (callback_url, sessiondata['session'], sessiondata['linkly_payment_id']),
            }
        }
        return self.proxy_linkly_request('/sendkey', headers, data)

    def _linkly_payment_status(self, sessiondata):
        callback_url = self.env['ir.config_parameter'].sudo().get_param('Your.Web.Url', False)
        headers = {
            'Authorization': self._linkly_get_token(),
            'Content-Type': 'application/json',
            'sessionId': sessiondata['session'],
            'livemode': self.get_linkly_mode()
        }
        data = {            
            'Notification':{
                'Uri': '%s/linkly/notification/0/0' % (callback_url),
            }}
        return self.proxy_linkly_request('/getpayment', headers, data)

    def proxy_linkly_request(self, service, headers, data):
        url = self.env['ir.config_parameter'].sudo().get_param('Havi.Api.Url.Linkly', False)
        if not url:
            self.raise_error('Please config Havi Api Url of Linkly (Havi.Api.Url.Linkly)')

        _logger.info('Request to linkly\n%s', pprint.pformat(data))
        TIMEOUT = self.linkly_time_out
        try:
            res = requests.post(url + service, verify=False, json=data, headers=headers)
        except requests.exceptions.Timeout: 
            self.raise_error ('Timeout: Request was cancelled.')
        except requests.exceptions.ConnectionError as ValueError:
            self.raise_error (ValueError)

        _logger.info('Response from linkly (HTTP status %s):\n%s', res.status_code, res.text)
        if res.status_code in (200, 201, 202):
            rt = json.loads(res.text)
            if rt['status'] in (200, 201, 202):
                rt['status'] = 200
            return rt
        else:
            self.raise_error(res.text)

    def correct_message(self, message):
        return message

    @api.model
    def _linkly_convert_amount(self, amount, currency):
        k = CURRENCY_CODE_MAPS.get(currency.name, 2)
        paymentAmount = int(tools.float_round(amount, k) * (10**k))
        return paymentAmount
        # return amount

class Payment_transaction(models.Model):
    _inherit = 'payment.transaction'

    linkly_response = fields.Char()
    linkly_session = fields.Char()
    journal_id = fields.Many2one('account.journal')

    def _create_payment(self, add_payment_vals={}):
        self.ensure_one()

        payment_vals = {
            'amount': self.amount,
            'payment_type': 'inbound' if self.amount > 0 else 'outbound',
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.commercial_partner_id.id,
            'partner_type': 'customer',
            'journal_id': self.journal_id.id or self.acquirer_id.journal_id.id,
            'company_id': self.acquirer_id.company_id.id,
            'payment_method_id': self.env.ref('payment.account_payment_method_electronic_in').id,
            'payment_token_id': self.payment_token_id and self.payment_token_id.id or None,
            'payment_transaction_id': self.id,
            'ref': self.reference,
            **add_payment_vals,
        }
        payment = self.env['account.payment'].create(payment_vals)
        payment.action_post()

        # Track the payment to make a one2one.
        self.payment_id = payment

        if self.invoice_ids:
            self.invoice_ids.filtered(lambda move: move.state == 'draft')._post()

            (payment.line_ids + self.invoice_ids.line_ids)\
                .filtered(lambda line: line.account_id == payment.destination_account_id and not line.reconciled)\
                .reconcile()

        return payment

class linkly_payment(models.Model):
    _name = "linkly.payment.register"

    linkly_response = fields.Char(default="0")
    linkly_session = fields.Char()
    journal_id = fields.Many2one('account.journal')
    communication = fields.Char(string="Memo")
    partner_id = fields.Many2one('res.partner', string="Customer/Vendor")
    currency_id = fields.Many2one('res.currency', string='Currency')
    amount = fields.Monetary(currency_field='currency_id')
    payment_register_id = fields.Integer(default=0)
    sale_order_ids = fields.Char(default="[]")
    is_process = fields.Boolean(default=False)

    def linkly_payment(self):
        self.linkly_session = str(uuid.uuid4())
        data = {
            'txnType': 'P',
            'amtPurchase': self.journal_id._linkly_convert_amount(abs(self.amount), self.currency_id),
            'txnRef': 'Pm %s' % self.id,
            'session': self.linkly_session,
            'linkly_payment_id': self.id,
        }
        return self.journal_id._linkly_payment(data)
                    
    def linkly_refund(self):
        self.linkly_session = str(uuid.uuid4())
        data = {
            'txnType': 'R',
            'amtPurchase': self.journal_id._linkly_convert_amount(abs(self.amount), self.currency_id),
            'txnRef': 'Pm %s' % self.id,
            'session': self.linkly_session,
            'linkly_payment_id': self.id,
        }
        return self.journal_id._linkly_refund(data)

    def linkly_payment_cancel(self):
        data = {
            'txnType': 'P',
            'amtPurchase': self.journal_id._linkly_convert_amount(abs(self.amount), self.currency_id),
            'txnRef': 'Pm %s' % self.id,
            'session': self.linkly_session,
            'linkly_payment_id': self.id,
        }
        return self.journal_id._linkly_payment_cancel(data)

    def linkly_payment_status(self):
        data = {
            'txnType': 'P',
            'amtPurchase': self.journal_id._linkly_convert_amount(abs(self.amount), self.currency_id),
            'txnRef': 'Pm %s' % self.id,
            'session': self.linkly_session,
            'linkly_payment_id': self.id,
        }
        return self.journal_id._linkly_payment_status(data)

    @api.model
    def prepare_create_values(self, data):
        values = {}
        for key, value in data.items():
            if type(value) == dict:
                if value.get('type', False) and value.get('type') == 'record':
                    values[key] = value.get('res_id')
                if value.get('type', False) and value.get('type') == 'list':
                    values[key] = [(6, 0, value.get('res_ids'))] 
            else:
                values[key] = value
        return values

    def linkly_sale_payment(self, data):
        self = self.create(self.prepare_create_values(data))
        res = self.linkly_payment()
        res['linkly_payment_id'] = self.id
        return res
    
    @api.model
    def get_payment_response(self, linkly_id):
        self = self.sudo().browse(linkly_id)
        try:
            message = json.loads(self.linkly_response.replace('\'','"').replace('None','false').replace('False', 'false').replace('True', 'true').replace(', "', ',\n"').replace('responseText', 'ResponseText').replace('success', 'Success').replace('cardType', 'CardType').replace('cardName', 'CardName').replace('displayText', 'DisplayText'))
            if 'ResponseText' in message and 'Success' in message:
                if message['Success']:
                    if not self.is_process:
                        self.process_transaction()
                    return {'status': 1, 'result': message['ResponseText']}
                else:
                    return {'status': -1, 'result': message['ResponseText']}
            if 'DisplayText' in message:
                return {"status": 0, 'result': message['DisplayText']}
        except Exception as e:
            error = _('Error: %s' % e)
            return {'status': 0, 'result': '%s ----- %s' % (error, self.linkly_response)}
        return {'status': 0, 'result': 'Processing...'}

    def process_transaction(self):
        try:
            if self.sale_order_ids != "[]":
                transaction = self.env['payment.transaction'].sudo()
                transaction = transaction.create({
                    'acquirer_id': self.journal_id.acquirer_id.id,
                    'linkly_response': self.linkly_response,
                    'linkly_session': self.linkly_session,
                    'type': 'form',
                    'return_url': 'Linkly',
                    # 'invoice_ids': [(6, 0, self._context.get('default_invoice_ids'))],
                    'sale_order_ids': [(6, 0, json.loads(self.sale_order_ids))],
                    'amount':  self.amount,
                    'currency_id': self.currency_id.id,
                    'journal_id': self.journal_id.id,
                    'partner_id': self.partner_id.id,
                    'partner_country_id': self.partner_id.country_id.id,
                    'reference': "%s - %s" %(self.communication, self.id) ,
                    'state': 'done',
                })
                if transaction.sale_order_ids:
                    transaction.sale_order_ids.with_context(default_journal_id=None).action_confirm()
                    transaction.invoice_ids = [(6, 0, transaction.invoice_ids.ids + transaction.sale_order_ids.mapped('invoice_ids').ids)]
                    transaction.with_context(default_journal_id=None)._post_process_after_done()
                self.is_process = True

            if self.payment_register_id != 0:
                register = self.env['account.payment.register'].browse(self.payment_register_id)
                if register:
                    transaction = self.env['payment.transaction'].sudo()
                    payments = register._create_payments()
                    transaction = transaction.create({
                        'acquirer_id': register.journal_id.acquirer_id.id,
                        'linkly_response': self.linkly_response,
                        'linkly_session': self.linkly_session,
                        'type': 'form',
                        'return_url': 'Linkly',
                        'amount':  register.amount,
                        'currency_id': register.currency_id.id,
                        'partner_id': register.partner_id.id,
                        'partner_country_id': register.partner_id.country_id.id,
                        'reference': register.communication,
                        'state': 'done',
                        'is_processed': True,
                    })
                    for payment in payments:
                        payment.payment_transaction_id = transaction.id
                    self.is_process = True

        except Exception as e:
            error = _('Error: %s' % e)
            raise ValidationError(error)

class payment_register(models.TransientModel):
    _inherit = "account.payment.register"

    use_payment_terminal = fields.Selection(related='journal_id.use_payment_terminal')

    def linkly_refund(self, data):
        self = self.create(self.env['linkly.payment.register'].prepare_create_values(data))
        linkly = self.env['linkly.payment.register'].create({
            'journal_id': self.journal_id.id,
            'amount': self.amount,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'communication': 'Credit Note %s' % self.communication,
            'payment_register_id': self.id,
        })
        res = linkly.linkly_refund()
        res['linkly_payment_id'] = linkly.id
        return res

    def linkly_payment(self, data):
        self = self.create(self.env['linkly.payment.register'].prepare_create_values(data))
        linkly = self.env['linkly.payment.register'].create({
            'journal_id': self.journal_id.id,
            'amount': self.amount,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'communication': 'Invoice %s' % self.communication,
            'payment_register_id': self.id,
        })
        res = linkly.linkly_payment()
        res['linkly_payment_id'] = linkly.id
        return res

class sale_order(models.Model):
    _inherit = 'sale.order'

    def linkly_payment_sale(self):
        return {
        'name': 'Total payment',
        'type': 'ir.actions.act_window',
        'view_type': 'form',
        'view_mode': 'form',
        'res_model': 'linkly.payment.register',
        'view_id': self.env.ref('hv_payment_linkly.view_linkly_payment_register_form').id,
        'target': 'new',
        'context':{
            'default_payment_register_id': 0,
            # 'default_invoice_ids': [],
            'default_sale_order_ids': json.dumps(self.ids),
            'default_journal_id': self.env['account.journal'].search([('use_payment_terminal', '=', 'linkly')], limit=1).id,
            'default_amount': self.amount_total,
            'default_partner_id': self[0].partner_id.id,
            'default_currency_id': self[0].pricelist_id.currency_id.id,
            'default_communication': 'Sale - %s' % self.name,
            }
        }

