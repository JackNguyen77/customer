odoo.define('hv_payment_linkly.linkly_payment_button', function (require) {
    'use strict';

    const widgetRegistry = require('web.widget_registry');
    const Widget = require('web.Widget');
    var framework = require('web.framework');
    var core = require('web.core');
    var QWeb = core.qweb;

    const linkly_payment_button = Widget.extend({
        template: 'hv_payment_linkly.linkly_payment_button',
        events: Object.assign({}, Widget.prototype.events, {
            'click': '_onClickButton',
        }),

        init: function (parent, data, node) {
            this._super(...arguments);
            this.button_name = node.attrs.button_name;
            this.title = node.attrs.title;
            this.id = data.res_id;
            this.model = data.model;
        },

        //--------------------------------------------------------------------------
        // Handlers
        //--------------------------------------------------------------------------
        _onClickButton: function (ev) {
            var self = this;
            $.blockUI({message: QWeb.render('Throbber')});
            $(document.body).addClass('o_ui_blocked');
            this._rpc({
                method: this.button_name,
                model: this.model,
                args: [[this.id], this.__parentedParent.state.data],
            }).then(res => {
                if (res.status == 200 || res.status == 201 || res.status == 202) {
                    self._get_status(res.linkly_payment_id)
                }else{
                    $(document.body).removeClass('o_ui_blocked');
                    $.unblockUI();
                    alert(res.result)
                }
            }).catch(res => {
                $(document.body).removeClass('o_ui_blocked');
                $.unblockUI();
            })
        },
        _get_status: function(linkly_payment_id){
            var self = this;
            if ($('.oe_throbber_message').length === 0){
                $.blockUI({message: QWeb.render('Throbber')});
                $(document.body).addClass('o_ui_blocked');
            }
            setTimeout(function() {
                self._rpc({
                    method: 'get_payment_response',
                    model: 'linkly.payment.register',
                    args: [linkly_payment_id],
                }).then(res => {
                    if (res.status === -1){
                        alert(res.result)
                        $(document.body).removeClass('o_ui_blocked');
                        $.unblockUI();
                        return
                    }
                    if (res.status === 1){
                        alert(res.result)
                        $(document.body).removeClass('o_ui_blocked');
                        $.unblockUI();
                        self.do_action({type: 'ir.actions.act_window_close'});
                        return
                    }
                    var $el = $('.oe_throbber_message');
                    $el.text(res.result);
                    self._get_status(linkly_payment_id)
                }).catch(res => {
                    $(document.body).removeClass('o_ui_blocked');
                    $.unblockUI();
                })
            }, 2000);
        }
    });

    widgetRegistry.add('linkly_payment_button', linkly_payment_button);

    return linkly_payment_button;
});
