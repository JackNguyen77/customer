# coding: utf-8
import logging
import pprint
import json
from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PosLinklyController(http.Controller):
    @http.route(['/hv_pos_linkly/notification/<string:uuid>/<int:linkly_payment_id>/'], type='json', auth='none', csrf=False)
    def hv_pos_linkly_notification(self, uuid='', linkly_payment_id=0, **kw):
        data = json.loads(request.httprequest.data)
        _logger.info('notification received from linkly:\n%s', pprint.pformat(data))
        terminal_identifier = data['SaleToPOIResponse']['MessageHeader']['POIID']
        payment_method = request.env['pos.payment.method'].sudo().search([('linkly_terminal_identifier', '=', terminal_identifier)], limit=1)
        
        if payment_method:
            # These are only used to see if the terminal is reachable,
            # store the most recent ID we received.
            if data['SaleToPOIResponse'].get('DiagnosisResponse'):
                payment_method.linkly_latest_diagnosis = data['SaleToPOIResponse']['MessageHeader']['ServiceID']
            else:
                payment_method.linkly_latest_response = json.dumps(data)
        else:
            _logger.error('received a message for a terminal not registered in Odoo: %s', terminal_identifier)
