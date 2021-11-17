
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    linkly_account_id = fields.Many2one(string='Linkly Account', related='company_id.linkly_account_id')

    def create_linkly_account(self):
        return self.env['linkly.account'].action_create_redirect()
