# -*- coding: utf-8 -*-
"""
    test_opportunity

    Test suite for crm

    :copyright: (c) 2013-2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
import sys
import os
import unittest
import datetime
import simplejson as json
from dateutil.relativedelta import relativedelta
DIR = os.path.abspath(os.path.normpath(
    os.path.join(
        __file__, '..', '..', '..', '..', '..', 'trytond')
    )
)
if os.path.isdir(DIR):
    sys.path.insert(0, os.path.dirname(DIR))

from mock import patch
from trytond.config import CONFIG
CONFIG['smtp_from'] = 'test@openlabs.co.in'

import trytond.tests.test_tryton
from trytond.tests.test_tryton import POOL, DB_NAME, USER, CONTEXT
from trytond.transaction import Transaction
from trytond.tests.test_tryton import test_view, test_depends
from nereid.testing import NereidTestCase


class NereidCRMTestCase(NereidTestCase):
    '''
    Test Nereid CRM module.
    '''

    def setUp(self):
        trytond.tests.test_tryton.install_module('nereid_crm')

        self.NereidWebsite = POOL.get('nereid.website')
        self.NereidPermission = POOL.get('nereid.permission')
        self.NereidUser = POOL.get('nereid.user')
        self.UrlMap = POOL.get('nereid.url_map')
        self.Company = POOL.get('company.company')
        self.Employee = POOL.get('company.employee')
        self.Currency = POOL.get('currency.currency')
        self.Country = POOL.get('country.country')
        self.Language = POOL.get('ir.lang')
        self.sale_opp_obj = POOL.get('sale.opportunity')
        self.User = POOL.get('res.user')
        self.Config = POOL.get('sale.configuration')
        self.Party = POOL.get('party.party')
        self.Locale = POOL.get('nereid.website.locale')
        self.xhr_header = [
            ('X-Requested-With', 'XMLHttpRequest'),
        ]

        # Patch SMTP Lib
        self.smtplib_patcher = patch('smtplib.SMTP', autospec=True)
        self.PatchedSMTP = self.smtplib_patcher.start()
        self.mocked_smtp_instance = self.PatchedSMTP.return_value

        self.templates = {
            'home.jinja': '{{get_flashed_messages()}}',
            'login.jinja':
            '{{ login_form.errors }} {{get_flashed_messages()}}',
            'crm/sale_form.jinja': ' ',
            'crm/leads.jinja': '{{leads|length}}',
            'crm/emails/lead_thank_you_mail.jinja': ' ',
            'crm/emails/sale_notification_text.jinja': ' ',
        }

    def tearDown(self):
        # Unpatch SMTP Lib
        self.smtplib_patcher.stop()

    def _create_fiscal_year(self, date=None, company=None):
        """Creates a fiscal year and requried sequences
        """
        FiscalYear = POOL.get('account.fiscalyear')
        Sequence = POOL.get('ir.sequence')
        SequenceStrict = POOL.get('ir.sequence.strict')
        Company = POOL.get('company.company')

        if date is None:
            date = datetime.date.today()

        if company is None:
            company, = Company.search([], limit=1)

        invoice_sequence, = SequenceStrict.create([{
            'name': '%s' % date.year,
            'code': 'account.invoice',
            'company': company,
        }])
        fiscal_year, = FiscalYear.create([{
            'name': '%s' % date.year,
            'start_date': date + relativedelta(month=1, day=1),
            'end_date': date + relativedelta(month=12, day=31),
            'company': company,
            'post_move_sequence': Sequence.create([{
                'name': '%s' % date.year,
                'code': 'account.move',
                'company': company,
            }])[0],
            'out_invoice_sequence': invoice_sequence,
            'in_invoice_sequence': invoice_sequence,
            'out_credit_note_sequence': invoice_sequence,
            'in_credit_note_sequence': invoice_sequence,
        }])
        FiscalYear.create_period([fiscal_year])
        return fiscal_year

    def _create_coa_minimal(self, company):
        """Create a minimal chart of accounts
        """
        AccountTemplate = POOL.get('account.account.template')
        Account = POOL.get('account.account')
        account_create_chart = POOL.get(
            'account.create_chart', type="wizard")

        account_template, = AccountTemplate.search(
            [('parent', '=', None)])

        session_id, _, _ = account_create_chart.create()
        create_chart = account_create_chart(session_id)
        create_chart.account.account_template = account_template
        create_chart.account.company = company
        create_chart.transition_create_account()

        receivable, = Account.search([
            ('kind', '=', 'receivable'),
            ('company', '=', company),
            ])
        payable, = Account.search([
            ('kind', '=', 'payable'),
            ('company', '=', company),
            ])
        create_chart.properties.company = company
        create_chart.properties.account_receivable = receivable
        create_chart.properties.account_payable = payable
        create_chart.transition_create_properties()

    def _get_account_by_kind(self, kind, company=None, silent=True):
        """Returns an account with given spec

        :param kind: receivable/payable/expense/revenue
        :param silent: dont raise error if account is not found
        """
        Account = POOL.get('account.account')
        Company = POOL.get('company.company')

        if company is None:
            company, = Company.search([], limit=1)

        accounts = Account.search([
            ('kind', '=', kind),
            ('company', '=', company)
            ], limit=1)
        if not accounts and not silent:
            raise Exception("Account not found")
        return accounts[0] if accounts else False

    def setup_defaults(self):
        '''
        Setup defaults for test
        '''
        usd, = self.Currency.create([{
            'name': 'US Dollar',
            'code': 'USD',
            'symbol': '$',
        }])
        self.Country.create([{
            'name': 'India',
            'code': 'IN',
        }])
        self.country, = self.Country.search([])

        with Transaction().set_context(company=None):
            company_party, = self.Party.create([{
                'name': 'Openlabs',
            }])
            self.company, = self.Company.create([{
                'party': company_party,
                'currency': usd,
            }])

        self.User.write([self.User(USER)], {
            'company': self.company,
            'main_company': self.company,
        })
        CONTEXT.update(self.User.get_preferences(context_only=True))

        self._create_fiscal_year(company=self.company.id)
        self._create_coa_minimal(company=self.company.id)

        admin_party1, = self.Party.create([{
            'name': 'Crm Admin',
        }])
        self.crm_admin, = self.NereidUser.create([{
            'party': admin_party1,
            'display_name': 'Crm Admin',
            'email': 'admin@openlabs.co.in',
            'password': 'password',
            'company': self.company.id,
        }])
        employee, = self.Employee.create([{
            'company': self.company.id,
            'party': self.crm_admin.party.id,
        }])

        self.Config.write([self.Config(1)], {'website_employee': employee.id})

        self.NereidUser.write([self.crm_admin], {
            'employee': employee.id,
        })

        admin_party2, = self.Party.create([{
            'name': 'Crm Admin2',
        }])

        self.crm_admin2, = self.NereidUser.create([{
            'party': admin_party2,
            'display_name': 'Crm Admin2',
            'email': 'admin2@openlabs.co.in',
            'password': 'password',
            'company': self.company.id,
        }])
        employee, = self.Employee.create([{
            'company': self.company.id,
            'party': self.crm_admin2.party.id,
        }])
        self.NereidUser.write([self.crm_admin2], {
            'employee': employee.id,
        })

        url_map, = self.UrlMap.search([], limit=1)
        en_us, = self.Language.search([('code', '=', 'en_US')])
        locale_en, = self.Locale.create([{
            'code': 'en_US',
            'language': en_us.id,
            'currency': usd.id,
        }])
        self.NereidWebsite.create([{
            'name': 'localhost',
            'url_map': url_map,
            'company': self.company,
            'application_user': USER,
            'default_locale': locale_en.id,
        }])

        perm_admin, = self.NereidPermission.search([
            ('value', '=', 'sales.admin'),
        ])
        self.NereidUser.write(
            [self.crm_admin], {'permissions': [('add', [perm_admin])]}
        )
        self.Company.write(
            [self.company], {'sales_team': [('add', [self.crm_admin])]}
        )

    def create_test_lead(self):
        '''
        Setup test sale
        '''
        self.setup_defaults()
        ContactMech = POOL.get('party.contact_mechanism')
        Party = POOL.get('party.party')
        # Create Party
        party, = Party.create([{
            'name': "abc",
            'addresses': [
                ('create', [{
                    'name': 'abc',
                    'country': self.country,
                }])
            ],
        }])

        # Create email as contact mech and assign as email
        ContactMech.create([{
            'type': 'email',
            'party': party.id,
            'email': 'client@example.com',
        }])

        # Create sale opportunity
        description = 'Created by %s' % self.crm_admin.display_name
        self.lead, = self.sale_opp_obj.create([{
            'party': party.id,
            'company': self.company,
            'employee': self.crm_admin.employee.id,
            'address': party.addresses[0].id,
            'description': description,
            'comment': 'comment',
            'ip_address': '127.0.0.1',
            'detected_country': '',
        }])

    def get_template_source(self, name):
        """
        Return templates
        """
        return self.templates.get(name)

    def test0005views(self):
        '''
        Test views.
        '''
        test_view('nereid_crm')

    def test0006depends(self):
        '''
        Test depends.
        '''
        test_depends()

    def test_0010_new_opportunity(self):
        """
        Test new_opportunity web handler
        """
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_client() as c:
                response = c.post(
                    '/sales/opportunity/-new',
                    data={
                        'company': 'ABC',
                        'name': 'Tarun',
                        'email': 'demo@example.com',
                        'comment': 'comment',
                    },
                    headers=self.xhr_header,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(json.loads(response.data)['success'])

    def test_0020_revenue_opportunity(self):
        '''
        Test revenue_opportunity web handler
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.create_test_lead()
            app = self.get_app()

            with app.test_client() as c:
                response = c.post(
                    '/login',
                    data={
                        'email': 'admin@openlabs.co.in',
                        'password': 'password',
                    }
                )
                self.assertEqual(response.status_code, 302)
                response = c.post(
                    '/sales/opportunity/lead-revenue/%d' % self.lead.id,
                    data={
                        'probability': 1,
                        'amount': 100,
                    }
                )
                self.assertEqual(response.status_code, 302)

    def test_0030_assign_lead(self):
        '''
        Test assign_lead
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.create_test_lead()
            app = self.get_app()

            with app.test_client() as c:
                response = c.post(
                    '/login',
                    data={
                        'email': 'admin@openlabs.co.in',
                        'password': 'password',
                    }
                )
                self.assertEqual(response.status_code, 302)
                response = c.post(
                    '/lead-%d/-assign' % self.lead.id,
                    data={
                        'user': self.crm_admin.id,
                    }
                )
                self.assertEqual(response.status_code, 302)
                response = c.get('/login')
                self.assertTrue(
                    "Lead already assigned to %s" % self.crm_admin.party.name
                    in response.data
                )
                response = c.post(
                    '/lead-%d/-assign' % self.lead.id,
                    data={
                        'user': self.crm_admin2.id,
                    }
                )
                self.assertEqual(response.status_code, 302)
                response = c.get('/login')
                self.assertTrue(
                    "Lead assigned to %s" % self.crm_admin2.party.name
                    in response.data
                )

    def test_0040_all_leads(self):
        '''
        Test all_leads
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.create_test_lead()
            app = self.get_app()

            with app.test_client() as c:
                response = c.post(
                    '/login',
                    data={
                        'email': 'admin@openlabs.co.in',
                        'password': 'password',
                    }
                )
                self.assertEqual(response.status_code, 302)
                response = c.get(
                    '/sales/opportunity/leads',
                )
                self.assertEqual(
                    response.data, u'1'
                )


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        NereidCRMTestCase))
    return suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
