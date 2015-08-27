# This file is part esale module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.modules.esale.tools import is_a_vat
import logging

logger = logging.getLogger(__name__)

try:
    import vatnumber
    HAS_VATNUMBER = True
except ImportError:
    logger.warning(
            'Unable to import vatnumber. VAT number validation disabled.')

__all__ = ['Party']
__metaclass__ = PoolMeta


class Party:
    __name__ = 'party.party'
    esale_email = fields.Char('E-Mail')

    @classmethod
    def view_attributes(cls):
        return super(Party, cls).view_attributes() + [
            ('//page[@id="esale"]', 'states', {
                    'invisible': ~Eval('esale_email'),
                    })]

    @classmethod
    def esale_create_party(self, shop, values):
        '''
        Create Party
        :param shop: obj
        :param values: dict
        return party object
        '''
        pool = Pool()
        Party = pool.get('party.party')
        ContactMechanism = pool.get('party.contact_mechanism')

        # Validate VAT
        if (values.get('vat_country') and values.get('vat_number') and
                HAS_VATNUMBER):
            vat_number = values.get('vat_number')
            vat_country = values.get('vat_country')

            vat_number = '%s%s' % (vat_country.upper(), vat_number)
            if not vatnumber.check_vat(vat_number):
                del values['vat_country']
        elif 'vat_country' in values:
            del values['vat_country']

        if 'country' in values and not values.get('country'):
            del values['country']

        #  Search party by:
        #  - Vat country + vat number
        #  - Vat number
        #  - Party eSale Email
        #  - Party Email
        party = None
        if shop.esale_get_party_by_vat:
            vat_number = values.get('vat_number')
            if (vat_number and is_a_vat(vat_number) and
                    values.get('vat_country')):
                parties = Party.search([
                    ('vat_country', '=', values.get('vat_country')),
                    ('vat_number', '=', values.get('vat_number')),
                    ], limit=1)
                if parties:
                    party, = parties
            if vat_number and is_a_vat(vat_number) and not party:
                parties = Party.search([
                    ('vat_number', '=', values.get('vat_number')),
                    ], limit=1)
                if parties:
                    party, = parties

        if not party:
            parties = Party.search([
                ('esale_email', '=', values.get('esale_email')),
                ], limit=1)
            if parties:
                party, = parties

        if not party:
            mechanisms = ContactMechanism.search([
                ('type', '=', 'email'),
                ('value', '=', values.get('esale_email')),
                ], limit=1)
            if mechanisms:
                mechanism, = mechanisms
                party = mechanism.party

        if not party:
            values['addresses'] = None
            party, = Party.create([values])
            logger.info('Shop %s. Create party ID %s' % (
                shop.name, party.id))
        return party
