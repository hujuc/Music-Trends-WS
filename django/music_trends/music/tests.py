from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class OperationsViewTests(TestCase):
	def setUp(self):
		self.url = reverse('operations')

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_add_genre_success(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'add_genre',
			'song_name': 'Existing Song',
			'genre': 'alt-pop',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Genre added successfully.')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_add_genre_song_not_found(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = []

		response = self.client.post(self.url, {
			'operation': 'add_genre',
			'song_name': 'Missing Song',
			'genre': 'alt-pop',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Song not found (exact name required).')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_edit_attribute_success(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'edit_attribute',
			'song_name': 'Existing Song',
			'attribute': 'energy',
			'value': '0.85',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Energy updated successfully.')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_edit_attribute_invalid_attribute(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'edit_attribute',
			'song_name': 'Existing Song',
			'attribute': 'loudness',
			'value': '0.85',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Invalid attribute. Allowed: energy, danceability, valence, acousticness, speechiness, instrumentalness, liveness, tempo.')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_edit_attribute_out_of_range(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'edit_attribute',
			'song_name': 'Existing Song',
			'attribute': 'energy',
			'value': '2.0',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Invalid value for energy (must be between 0.0 and 1.0).')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_remove_featured_success(self, mock_run_select, mock_run_update):
		mock_run_select.side_effect = [
			[],
			[],
			[],
			[],
			[{'song': {'value': 'http://music.org/song/1'}}],
			[{'feat': {'value': 'http://music.org/artist/feat1'}}],
		]

		response = self.client.post(self.url, {
			'operation': 'remove_featured',
			'song_name': 'Existing Song',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Featured artists removed successfully.')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_remove_featured_without_featured_relation(self, mock_run_select, mock_run_update):
		mock_run_select.side_effect = [
			[],
			[],
			[],
			[],
			[{'song': {'value': 'http://music.org/song/1'}}],
			[],
		]

		response = self.client.post(self.url, {
			'operation': 'remove_featured',
			'song_name': 'Existing Song',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Song has no featured artists to remove.')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_add_chart_entry_success(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'add_chart_entry',
			'song_name': 'Existing Song',
			'rank': '10',
			'weeks': '12',
			'date': '2026-04-13',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Chart entry added successfully.')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_add_chart_entry_invalid_rank_or_weeks(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'add_chart_entry',
			'song_name': 'Existing Song',
			'rank': '0',
			'weeks': '-1',
			'date': '2026-04-13',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Invalid rank or weeks (must be positive integers).')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_add_chart_entry_invalid_date(self, mock_run_select, mock_run_update):
		mock_run_select.return_value = [{'song': {'value': 'http://music.org/song/1'}}]

		response = self.client.post(self.url, {
			'operation': 'add_chart_entry',
			'song_name': 'Existing Song',
			'rank': '10',
			'weeks': '12',
			'date': '2026/04/13',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Invalid date format (expected YYYY-MM-DD).')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	def test_remove_chart_entry_success(self, mock_run_update):
		response = self.client.post(self.url, {
			'operation': 'remove_chart_entry',
			'entry_uri': 'http://music.org/entry/manual-abc123',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Chart entry removed successfully.')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	def test_remove_chart_entry_invalid_uri(self, mock_run_update):
		response = self.client.post(self.url, {
			'operation': 'remove_chart_entry',
			'entry_uri': 'not-a-valid-uri',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Invalid chart entry URI.')
		mock_run_update.assert_not_called()

	@patch('music.views.run_select')
	def test_run_validation_base_list(self, mock_run_select):
		mock_run_select.return_value = [
			{
				'songName': {'value': 'Song A'},
				'artistName': {'value': 'Artist A'},
				'song': {'value': 'http://music.org/song/a'},
			}
		]

		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'base_list',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Validation query executed: base_list.')
		self.assertContains(response, 'Song A')

	@patch('music.views.run_select')
	def test_run_validation_by_artist(self, mock_run_select):
		mock_run_select.return_value = [
			{'songName': {'value': 'Song B'}, 'genre': {'value': 'pop'}}
		]

		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'by_artist',
			'artist_name': 'Artist B',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Validation query executed: by_artist.')
		self.assertContains(response, 'Song B')

	@patch('music.views.run_select')
	def test_run_validation_by_artist_missing_name(self, mock_run_select):
		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'by_artist',
			'artist_name': '',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Artist name is required for artist validation.')
		self.assertEqual(mock_run_select.call_count, 4)

	@patch('music.views.run_select')
	def test_run_validation_by_genre(self, mock_run_select):
		mock_run_select.return_value = [
			{
				'songName': {'value': 'Song C'},
				'artistName': {'value': 'Artist C'},
				'energy': {'value': '0.80'},
				'danceability': {'value': '0.75'},
			}
		]

		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'by_genre',
			'genre': 'pop',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Validation query executed: by_genre.')
		self.assertContains(response, 'Song C')

	@patch('music.views.run_select')
	def test_run_validation_by_genre_missing_genre(self, mock_run_select):
		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'by_genre',
			'genre': '',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Genre is required for genre validation.')
		self.assertEqual(mock_run_select.call_count, 4)

	@patch('music.views.run_select')
	def test_run_validation_unknown_type(self, mock_run_select):
		response = self.client.post(self.url, {
			'operation': 'run_validation',
			'validation_type': 'unknown_type',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Unknown validation query type.')
		self.assertEqual(mock_run_select.call_count, 4)

	def test_unknown_operation(self):
		response = self.client.post(self.url, {
			'operation': 'not_existing_operation',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Unknown operation.')


class ChartEntryResolutionTests(TestCase):
	def setUp(self):
		self.url = reverse('operations')

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_chart_edit_resolves_entry_by_song_and_date(self, mock_run_select, mock_run_update):
		mock_run_select.side_effect = [
			[],  # song options preload
			[],  # artist options preload
			[],  # genre options preload
			[],  # chart entry options preload
			[{'entry': {'value': 'http://music.org/entry/manual-abc123'}}],  # resolve by song+date
			[{'entry': {'value': 'http://music.org/entry/manual-abc123'}}],  # entry exists check
		]

		response = self.client.post(self.url, {
			'operation': 'chart_edit',
			'song_name': 'ugo',
			'current_date': '2026-04-07',
			'rank': '2',
			'weeks': '5',
			'date': '2026-04-14',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Chart entry updated successfully (rank, weeks and date).')
		mock_run_update.assert_called_once()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_chart_edit_by_song_and_date_not_found(self, mock_run_select, mock_run_update):
		mock_run_select.side_effect = [
			[],  # song options preload
			[],  # artist options preload
			[],  # genre options preload
			[],  # chart entry options preload
			[],  # resolve by song+date -> not found
		]

		response = self.client.post(self.url, {
			'operation': 'chart_edit',
			'song_name': 'ugo',
			'current_date': '2026-04-07',
			'rank': '2',
			'date': '2026-04-14',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Chart entry not found or invalid reference.')
		mock_run_update.assert_not_called()

	@patch('music.views.run_update')
	@patch('music.views.run_select')
	def test_chart_edit_by_song_and_date_ambiguous(self, mock_run_select, mock_run_update):
		mock_run_select.side_effect = [
			[],  # song options preload
			[],  # artist options preload
			[],  # genre options preload
			[],  # chart entry options preload
			[
				{'entry': {'value': 'http://music.org/entry/manual-1'}},
				{'entry': {'value': 'http://music.org/entry/manual-2'}},
			],  # resolve by song+date -> ambiguous
		]

		response = self.client.post(self.url, {
			'operation': 'chart_edit',
			'song_name': 'ugo',
			'current_date': '2026-04-07',
			'rank': '2',
			'date': '2026-04-14',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'More than one chart entry found for this song/date. Please use ChartEntry URI.')
		mock_run_update.assert_not_called()
