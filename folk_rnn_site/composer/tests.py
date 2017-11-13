from django.test import TestCase
from django.urls import resolve
from django.http import HttpRequest
from django.utils.timezone import now
from datetime import timedelta
from time import sleep
from email.utils import format_datetime # RFC 2822 for parity with django template date filter

from composer.views import composer_page
from composer.models import Tune

class HomePageTest(TestCase):
    
    def post_tune(self):
        return self.client.post('/', data={'meter':'M:4/4', 'key': 'K:Cmaj', 'seed': 'some ABC notation'})
    
    def test_compose_page_uses_compose_template(self):
        response = self.client.get('/')  
        self.assertTemplateUsed(response, 'compose.html')
    
    def test_compose_page_can_save_a_POST_request(self):
        self.post_tune()
        
        self.assertEqual(Tune.objects.count(), 1)
        new_tune = Tune.objects.first()
        self.assertEqual(new_tune.seed, 'M:4/4 K:Cmaj some ABC notation')
    
    def test_compose_page_redirects_after_POST(self):
        response = self.post_tune()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['location'], '/candidate-tune/1')
    
    def test_candidate_tune_path_with_no_id_fails_gracefully(self):
        response = self.client.get('/candidate-tune/')
        self.assertEqual(response['location'], '/')
    
    def test_candidate_tune_path_with_invalid_id_fails_gracefully(self):
        response = self.client.get('/candidate-tune/1')
        self.assertEqual(response['location'], '/')
    
    def test_candidate_tune_page_uses_candidate_tune_template(self):
        self.post_tune()
        response = self.client.get('/candidate-tune/1')
        self.assertTemplateUsed(response, 'candidate-tune-in-process.html')
        
    def test_candidate_tune_page_shows_composing_messages(self):
        self.post_tune()
        response = self.client.get('/candidate-tune/1')
        self.assertContains(response, 'Composition with seed "M:4/4 K:Cmaj some ABC notation" is waiting for folk_rnn task')
        
        tune = Tune.objects.first()
        tune.rnn_started = now()
        tune.save()
        
        response = self.client.get('/candidate-tune/1')
        self.assertContains(response, 'Composition with seed "M:4/4 K:Cmaj some ABC notation" in process...')

    def test_candidate_tune_page_shows_results(self):
        self.post_tune()
        
        tune = Tune.objects.first()
        tune.seed = "seed ABC"
        tune.rnn_started = now()
        tune.rnn_finished = now() + timedelta(seconds=1)
        tune.rnn_tune = 'RNN ABC'
        tune.save()
        
        response = self.client.get('/candidate-tune/1')
        print(response.content)
        self.assertContains(response,'<p>The composition –<br>RNN ABC</p>', html=True) # 'html' needed to handle linebreak formatting
        self.assertContains(response,'<li>Seed: seed ABC</li>')
        self.assertContains(response,'<li>Requested at: {}</li>'.format(format_datetime(tune.requested)), msg_prefix='FIXME: This will falsely fail for single digit day of the month due to Django template / Python RFC formatting mis-match.') # FIXME
        self.assertContains(response,'<li>Composition took: 1s</li>')

class TuneModelTest(TestCase):
    
    def assertAlmostEqual(self, a, b, max_delta=0.1):
        delta = abs(a - b)
        self.assertTrue(delta < max_delta)
    
    def test_saving_and_retrieving_tunes(self):
        first_tune = Tune()
        first_tune.seed = 'ABC'
        first_tune.save()
        
        second_tune = Tune()
        second_tune.seed = 'DEF'
        second_tune.save()
        
        saved_tunes = Tune.objects.all()
        self.assertEqual(saved_tunes.count(), 2)
        
        first_saved_tune = saved_tunes[0]
        second_saved_tune = saved_tunes[1]
        self.assertEqual(first_saved_tune.seed, 'ABC')
        self.assertEqual(second_saved_tune.seed, 'DEF')
    
    def test_tune_lifecycle(self):
        tune = Tune.objects.create()
        self.assertAlmostEqual(tune.requested, now(), timedelta(seconds=0.1))
        self.assertEqual(tune.rnn_tune, '')
        
        tune = Tune.objects.first()
        tune.rnn_started = now()
        tune.save()
        
        sleep(0.001)
        
        tune = Tune.objects.first()
        tune.rnn_finished = now()
        tune.rnn_tune = 'RNN ABC'
        tune.save()
        
        tune = Tune.objects.first()
        self.assertTrue(tune.rnn_started < tune.rnn_finished)
        self.assertAlmostEqual(tune.rnn_started, tune.rnn_finished, timedelta(seconds=0.1))
        self.assertEqual(tune.rnn_tune, 'RNN ABC')
    