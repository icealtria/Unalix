from unalix import clear_url

def test_clear_url():

	unmodified_url = "https://deezer.com/track/891177062?utm_source=deezer"

	assert clear_url(unmodified_url) == "https://deezer.com/track/891177062"
	assert clear_url(unmodified_url, ignoreRules=True) == unmodified_url
	
	unmodified_url = "https://www.google.com/url?q=https://pypi.org/project/Unalix"

	assert clear_url(unmodified_url) == "https://pypi.org/project/Unalix"
	assert clear_url(unmodified_url, ignoreRedirections=True) == unmodified_url
	
	unmodified_url = "https://www.amazon.com/gp/B08CH7RHDP/ref=as_li_ss_tl"

	assert clear_url(unmodified_url) == "https://www.amazon.com/gp/B08CH7RHDP"
	assert clear_url(unmodified_url, ignoreRawRules=True) == unmodified_url
	
	unmodified_url = "http://0.0.0.0/?utm_source=local"

	assert clear_url(unmodified_url) == "http://0.0.0.0/"
	assert clear_url(unmodified_url, skipLocal=True) == unmodified_url
	
	unmodified_url = "https://natura.com.br/p/2458?consultoria=promotop"

	assert clear_url(unmodified_url) == "https://natura.com.br/p/2458"
	assert clear_url(unmodified_url, ignoreReferralMarketing=True) == unmodified_url

	unmodified_url = "https://myaccount.google.com/?utm_source=google"

	assert clear_url(unmodified_url) == unmodified_url
	assert clear_url(unmodified_url, ignoreExceptions=True) == "https://myaccount.google.com/"

	unmodified_url = "http://clickserve.dartsearch.net/link/click?ds_dest_url=http://g.co/"

	assert clear_url(unmodified_url) == "http://g.co/"
	assert clear_url(unmodified_url, skipBlocked=True) == unmodified_url

	unmodified_url = "http://example.com/?p1=&p2="

	assert clear_url(unmodified_url) == "http://example.com/?p1=&p2="
	assert clear_url(unmodified_url, stripEmpty=True) == "http://example.com/"

	unmodified_url = "http://example.com/?p1=value&p1=othervalue"

	assert clear_url(unmodified_url) == "http://example.com/?p1=value&p1=othervalue"
	assert clear_url(unmodified_url, stripDuplicates=True) == "http://example.com/?p1=value"

	unmodified_url = "http://example.com/?&&&&"

	assert clear_url(unmodified_url) == "http://example.com/"
