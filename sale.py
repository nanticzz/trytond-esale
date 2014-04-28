#This file is part esale module for Tryton.
#The COPYRIGHT file at the top level of this repository contains 
#the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

import logging

__all__ = ['Sale', 'SaleLine']
__metaclass__ = PoolMeta


class Sale:
    __name__ = 'sale.sale'
    reference_external = fields.Char('External Reference', readonly=True, select=True)
    status = fields.Char('Status', readonly=True,
        help='Last status import/export to e-commerce APP')
    status_history = fields.Text('Status history', readonly=True)

    @classmethod
    def create_external_order(self, shop, sale_values, lines_values,
            extralines_values, party_values, invoice_values, shipment_values):
        '''
        Create external order in sale
        :param shop: obj
        :param sale_values: dict
        :param lines_values: list
        :param party_values: dict
        :param invoice_values: dict
        :param shipment_values: dict
        '''
        pool = Pool()
        Sale = pool.get('sale.sale')
        Line = pool.get('sale.line')
        Party = pool.get('party.party')
        Address = pool.get('party.address')
        eSaleCarrier = pool.get('esale.carrier')
        eSalePayment = pool.get('esale.payment')
        eSaleStatus = pool.get('esale.status')
        Currency = Pool().get('currency.currency')

        #Default Sale values
        sale_values['shop'] = shop
        sale_values['warehouse'] = shop.warehouse

        #Create party
        party = Party.esale_create_party(shop, party_values)

        #Create address
        invoice_address = None
        if not ((invoice_values.get('street') == shipment_values.get('street')) and \
                (invoice_values.get('zip') == shipment_values.get('zip'))):
            invoice_address = Address.esale_create_address(shop, party, 
                invoice_values, type='invoice')
            shipment_address = Address.esale_create_address(shop, party,
                shipment_values, type='delivery')
        else:
            shipment_address = Address.esale_create_address(shop, party,
                shipment_values)

        #Party - Address
        sale_values['party'] = party
        sale_values['invoice_address'] = invoice_address or shipment_address
        sale_values['shipment_address'] = shipment_address

        #Order reference
        if shop.esale_ext_reference:
            sale_values['reference'] = sale_values.get('reference_external')

        #Currency
        currencies = Currency.search([
                ('code', '=', sale_values.get('currency')),
                ], limit=1)
        if currencies:
            sale_values['currency'] = currencies[0].id
        else:
            sale_values['currency'] = shop.esale_currency.id

        #Payment
        if sale_values.get('payment'):
            payments = eSalePayment.search([
                    ('code', '=', sale_values.get('payment')),
                    ('shop', '=', shop.id),
                    ], limit=1)
            if payments:
                sale_values['payment_type'] = payments[0].payment_type
        del sale_values['payment']

        #Status
        status = eSaleStatus.search([
                ('code', '=', sale_values.get('status')),
                ('shop', '=', shop.id),
                ], limit=1)
        if status:
            sale_status = status[0]
            sale_values['invoice_method'] = sale_status.invoice_method
            sale_values['shipment_method'] = sale_status.shipment_method

        #Lines
        sale = Sale()
        sale.shop = shop
        sale.party = party
        sale.currency = sale_values.get('currency')
        line = Line()
        line.party = party
        line.sale = sale
        lines = Line.esale_dict2lines(sale, line, lines_values)

        #Carrier + delivery line
        carriers = eSaleCarrier.search([
            ('code', '=', sale_values.get('carrier')),
            ('shop', '=', shop.id),
            ], limit=1)
        if carriers:
            carrier = carriers[0].carrier
            sale_values['carrier'] = carrier
            product_delivery = carrier.carrier_product
            shipment_description = carrier.rec_name
        else:
            del sale_values['carrier']
            product_delivery = shop.esale_delivery_product
            shipment_description = product_delivery.name
        shipment_values = [{
                'product': product_delivery.code or product_delivery.name,
                'quantity': 1,
                'description': shipment_description,
                'unit_price': sale_values.get('shipping_price', 0),
                'note': sale_values.get('shipping_note'),
                'shipment_cost': sale_values.get('shipping_price', 0),
                'sequence': 9999,
                }]
        shipment_line = Line.esale_dict2lines(sale, line, shipment_values)[0]
        sale_values['shipment_cost_method'] = 'order' # force shipment invoice on order
        del sale_values['shipping_price']
        del sale_values['shipping_note']

        # Surcharge
        surchage_line = None
        if sale_values.get('surcharge') and sale_values.get('surcharge') != 0.0000:
            surcharge_price = Decimal(sale_values.get('surcharge', 0))
            if shop.esale_surcharge_tax_include:
                for tax in shop.esale_surcharge_product.customer_taxes_used:
                    if tax.type == 'fixed':
                        surcharge_price = surcharge_price - tax.amount
                    if tax.type == 'percentage':
                        tax_price = surcharge_price-(surcharge_price/(1+(tax.rate)))
                        surcharge_price = surcharge_price - tax_price
                surcharge_price = Decimal('%.4f' % (surcharge_price))
            surcharge_values = [{
                    'product': shop.esale_surcharge_product.code or \
                            shop.esale_surcharge_product.name,
                    'quantity': 1,
                    'description': shop.esale_surcharge_product.name,
                    'unit_price': surcharge_price,
                    'sequence': 9999,
                    }]
            surchage_line = Line.esale_dict2lines(sale, line, surcharge_values)[0]
            del sale_values['surcharge']

        #Discount line
        discount_line = None
        if sale_values.get('discount') and sale_values.get('discount') != 0.0000:
            discount_values = [{
                    'product': shop.esale_discount_product.code or \
                            shop.esale_discount_product.name,
                    'quantity': 1,
                    'description': shop.esale_discount_product.name,
                    'unit_price': Decimal(sale_values.get('discount', 0)),
                    'sequence': 9999,
                    }]
            discount_line = Line.esale_dict2lines(sale, line, discount_values)[0]
        del sale_values['discount']

        extralines = None
        if extralines_values:
            extralines = Line.esale_dict2lines(sale, line, extralines_values)

        #Add lines
        lines.append(shipment_line)
        if discount_line:
            lines.append(discount_line)
        if surchage_line:
            lines.append(surchage_line)
        if extralines:
            lines = lines.copy()
            lines = lines + extralines
        sale_values['lines'] = [('create', lines)]

        #Default sale values
        sale_fields = Sale.fields_get()
        for k, v in Sale.default_get(sale_fields, with_rec_name=False).iteritems():
            if k not in sale_values:
                sale_values[k] = v

        #Create Sale
        Transaction().cursor.commit() #TODO: Add because get error when save order: could not serialize access due to concurrent update
        with Transaction().set_user(1, set_context=True): #TODO: force admin user create sale
            sale, = Sale.create([sale_values])
        logging.getLogger('esale').info(
            'Shop %s. Create sale %s' % (shop.name, sale.reference_external))

        if status:
            if sale_status.confirm:
                Sale.quote([sale])
                Sale.confirm([sale])
                logging.getLogger('esale').info(
                    'Confirm sale %s' % (sale.reference_external))
            if sale_status.cancel:
                Sale.cancel([sale])
                logging.getLogger('esale').info(
                    'Cancel sale %s' % (sale.reference_external))


class SaleLine:
    __name__ = 'sale.line'

    @classmethod
    def esale_dict2lines(self, sale, line, values):
        '''
        Return list sale lines
        :param sale: obj
        :param line: obj
        :param values: dict
        return list
        '''
        Product = Pool().get('product.product')

        def default_create_product(shop, code):
            return None

        lines = []
        for l in values:
            code = l.get('product')
            products = Product.search(['OR',
                    ('name', '=', code),
                    ('code', '=', code),
                    ], limit=1)
            if products:
                product, = products
            else:
                product_esale = getattr(Product, 
                    'create_product_%s' % sale.shop.esale_shop_app,
                    default_create_product)
                product = product_esale(sale.shop, code)

            # exist product
            if product:
                l['product'] = product

                line.product = product
                line.unit = product.default_uom
                line.quantity = l['quantity']
                line.description = product.name
                product_values = line.on_change_product()

                taxes = None
                if product_values.get('taxes'):
                    taxes = product_values.get('taxes')
                if not taxes:
                    taxes = product.customer_taxes_used

                l['taxes'] = [('add', taxes)]
                l['unit'] = product.default_uom
                l['description'] = product.rec_name
                for k, v in product_values.iteritems():
                    if k not in l:
                        l[k] = v
            # not exist product
            else:
                del l['product']
                l['unit'] = sale.shop.esale_uom_product
            lines.append(l)
        return lines
