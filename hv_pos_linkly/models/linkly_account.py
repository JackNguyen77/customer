# -*- coding: utf-8 -*-

import uuid
from werkzeug.urls import url_join

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class LinklyAccount(models.Model):
    _inherit = 'linkly.account'

    store_ids = fields.One2many('linkly.store', 'linkly_account_id')
    terminal_ids = fields.One2many('linkly.terminal', 'linkly_account_id')

    @api.model
    def _sync_linkly_cron(self):
        self.env['linkly.terminal']._sync_linkly_terminals()
        super(LinklyAccount, self)._sync_linkly_cron()

    def action_order_terminal(self):
        if not self.store_ids:
            raise ValidationError(_('Please create a store first.'))

        store_uuids = ','.join(self.store_ids.mapped('store_uuid'))
        onboarding_url = self.env['ir.config_parameter'].sudo().get_param('linkly_platforms.onboarding_url')
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': url_join(onboarding_url, 'order_terminals?store_uuids=%s' % store_uuids),
        }


class LinklyStore(models.Model):
    _name = 'linkly.store'
    _inherit = ['linkly.address.mixin']
    _description = 'Linkly for Platforms Store'

    linkly_account_id = fields.Many2one('linkly.account', ondelete='cascade')
    store_reference = fields.Char('Reference', default=lambda self: uuid.uuid4().hex)
    store_uuid = fields.Char('UUID', readonly=True) # Given by Linkly
    name = fields.Char('Name', required=True)
    phone_number = fields.Char('Phone Number', required=True)
    terminal_ids = fields.One2many('linkly.terminal', 'store_id', string='Payment Terminals', readonly=True)

    @api.model
    def create(self, values):
        linkly_store_id = super(LinklyStore, self).create(values)
        response = linkly_store_id.linkly_account_id._linkly_rpc('create_store', linkly_store_id._format_data())
        stores = response['accountHolderDetails']['storeDetails']
        created_store = next(store for store in stores if store['storeReference'] == linkly_store_id.store_reference)
        linkly_store_id.with_context(update_from_linkly=True).sudo().write({
            'store_uuid': created_store['store'],
        })
        return linkly_store_id

    def unlink(self):
        for store_id in self:
            store_id.linkly_account_id._linkly_rpc('close_stores', {
                'accountHolderCode': store_id.linkly_account_id.account_holder_code,
                'stores': [store_id.store_uuid],
            })
        return super(LinklyStore, self).unlink()

    def _format_data(self):
        return {
            'accountHolderCode': self.linkly_account_id.account_holder_code,
            'accountHolderDetails': {
                'storeDetails': [{
                    'storeReference': self.store_reference,
                    'storeName': self.name,
                    'merchantCategoryCode': '7999',
                    'address': {
                        'city': self.city,
                        'country': self.country_id.code,
                        'houseNumberOrName': self.house_number_or_name,
                        'postalCode': self.zip,
                        'stateOrProvince': self.state_id.code or None,
                        'street': self.street,
                    },
                    'fullPhoneNumber': self.phone_number,
                }],
            }
        }


class LinklyTerminal(models.Model):
    _name = 'linkly.terminal'
    _description = 'Linkly for Platforms Terminal'
    _rec_name = 'terminal_uuid'

    linkly_account_id = fields.Many2one('linkly.account', ondelete='cascade')
    store_id = fields.Many2one('linkly.store')
    terminal_uuid = fields.Char('Terminal ID')

    @api.model
    def _sync_linkly_terminals(self):
        for linkly_store_id in self.env['linkly.store'].search([]):
            response = linkly_store_id.linkly_account_id._linkly_rpc('connected_terminals', {
                'store': linkly_store_id.store_uuid,
            })
            terminals_in_db = set(self.search([('store_id', '=', linkly_store_id.id)]).mapped('terminal_uuid'))

            # Added terminals
            for terminal in set(response.get('uniqueTerminalIds')) - terminals_in_db:
                self.sudo().create({
                    'linkly_account_id': linkly_store_id.linkly_account_id.id,
                    'store_id': linkly_store_id.id,
                    'terminal_uuid': terminal,
                })
