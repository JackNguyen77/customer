from requests.sessions import session
from odoo.addons.portal.controllers.portal import get_records_pager, pager as portal_pager, CustomerPortal
from odoo.tools.translate import _
from werkzeug.exceptions import NotFound
from dateutil.relativedelta import relativedelta
from odoo import http
from odoo.addons.payment.controllers.portal import PaymentProcessing
from odoo.http import request
import base64
import json
import binascii
from collections import OrderedDict
import hashlib
import hmac
import logging
import random
import string
import pprint
import werkzeug
from unicodedata import normalize
from odoo.osv import expression
from odoo.tools.float_utils import float_repr

from itertools import chain

from werkzeug import urls

from odoo import api, fields, models, tools, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.tools.pycompat import to_text
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, ustr
import datetime
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class LinklyController(http.Controller):

    # @http.route(['/linkly/notification/<string:uuid>/<int:linkly_payment_id>/'], type='json', auth='none', csrf=False)
    @http.route(['/linkly/notification/<string:uuid>/<int:linkly_payment_id>/'], type='json', auth='public', website=True)
    def linkly_notify(self, uuid='', linkly_payment_id=0, **kw):
        data = json.loads(request.httprequest.data)
        linkly = request.env['linkly.payment.register'].sudo().browse(linkly_payment_id)
        if linkly:
            linkly.linkly_response = data['Response']
        return
