
import json
import logging
import pprint
import random
import requests
import string
import uuid
import sys
from werkzeug.exceptions import Forbidden

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class linkly_payment(models.Model):
    _inherit = "linkly.payment.register"

    pos_uid = fields.Char(default=False)
    pos_order_id = fields.Many2one(
        'pos.order', string='Order', compute="_compute_pos_order_id")

    def _compute_pos_order_id(self):
        for item in self:
            item.pos_order_id = False or self.env['pos.order'].search(
                [('pos_reference', '=', item.pos_uid)], limit=1).id if item.pos_uid else False


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super(PosPaymentMethod, self)._get_payment_terminal_selection() + [('linkly', 'Linkly')]

    # Linkly
    linkly_journal_id = fields.Many2one('account.journal', string='Linkly Journal', domain=[('use_payment_terminal', '=', 'linkly')], ondelete='restrict', help='The payment method is of type cash. A cash statement will be automatically generated.')
    linkly_terminal = fields.Char(related="linkly_journal_id.name")

    @api.constrains('linkly_journal_id')
    def _check_adyen_terminal_identifier(self):
        for payment_method in self:
            if not payment_method.linkly_journal_id:
                continue
            existing_payment_method = self.search([('id', '!=', payment_method.id),
                                                   ('linkly_journal_id', '=', payment_method.linkly_journal_id.id)],
                                                  limit=1)
            if existing_payment_method:
                raise ValidationError(_('Journal %s is already used on payment method %s.')
                                      % (payment_method.linkly_terminal, existing_payment_method.display_name))

    @api.onchange('use_payment_terminal')
    def _onchange_use_payment_terminal(self):
        super(PosPaymentMethod, self)._onchange_use_payment_terminal()
        if self.use_payment_terminal != 'linkly':
            self.linkly_journal_id = False

    # def _is_write_forbidden(self, fields):
    #     whitelisted_fields = set(('linkly_latest_response', 'linkly_latest_diagnosis'))
    #     return super(PosPaymentMethod, self)._is_write_forbidden(fields - whitelisted_fields)

    def pos_linkly_payment(self, data, operation=False):
        linkly = self.env['linkly.payment.register'].sudo().create({
            'journal_id': self.linkly_journal_id.id,
            'amount': data['RequestedAmount'],
            'currency_id': data['Currency'],
            'communication': 'POS %s' % data['TransactionID'],
            'pos_uid': data['TransactionID'],
        })
        res = linkly.with_context(call_from_pos=True).linkly_payment()
        res['linkly_payment_id'] = linkly.id
        return res

    def pos_linkly_payment_cancel(self, linkly_id):
        linkly = self.env['linkly.payment.register'].sudo().browse(linkly_id)
        res = linkly.with_context(call_from_pos=True).linkly_payment_cancel()
        res['linkly_payment_id'] = linkly.id
        return res

    def pos_linkly_payment_status(self, linkly_id):
        linkly = self.env['linkly.payment.register'].sudo().browse(linkly_id)
        res = linkly.with_context(call_from_pos=True).linkly_payment_status()
        if res['status']==200:
            if 'response' in res['result']:
                linkly.linkly_response = res['result']['response']
        res['linkly_payment_id'] = linkly.id
        return res

    def get_latest_linkly_status(self, linkly_id):
        linkly = self.env['linkly.payment.register'].sudo().browse(linkly_id)
        try:
            message = json.loads(linkly.linkly_response.replace('\'','"').replace('None','false').replace('False', 'false').replace('True', 'true').replace(', "', ',\n"').replace('responseText', 'ResponseText').replace('success', 'Success').replace('cardType', 'CardType').replace('cardName', 'CardName').replace('displayText', 'DisplayText'))
            if 'ResponseText' in message and 'Success' in message:
                if message['Success']:
                    return {
                        'status': 1, 'result': message['ResponseText'], 
                        'transaction_id':  linkly.id, 
                        'card_type':  message['CardType'], 
                        'card_name':  message['CardName'], 
                    }
                else:
                    return {'status': -1, 'result': message['ResponseText']}
            if 'DisplayText' in message:
                return {"status": 0, 'result': message['DisplayText']}
        except Exception as e:
            error = _('Error: %s' % e)
            # return {'status': 0, 'result': '%s ----- %s' % (error, linkly.linkly_response)}
        return {'status': 0, 'result': 'Processing...'}
