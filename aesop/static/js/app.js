var aesopApp = angular.module('aesopApp',
  ['ui.router', 'ngWebSocket', 'ui.bootstrap', 'ui.select', 'ngSanitize', 'ngTouch',
   'angular-growl']);

function wsPath(resource) {
    var loc = window.location, new_uri;
    new_uri = "ws:";
    new_uri += "//" + loc.host;
    new_uri += loc.pathname + resource;
    return new_uri;
}

aesopApp.factory('focus', function($timeout) {
  return function(id) {
    // timeout makes sure that it is invoked after any other event has been triggered.
    // e.g. click events that need to run before the focus or
    // inputs elements that are in a disabled state but are enabled when those events
    // are triggered.
    $timeout(function() {
      var element = document.getElementById(id);
      if(element)
        element.focus();
    });
  };
})
angular.module("ngTouchend", []).directive("ngTouchend", function () {
  return {
    controller: function ($scope, $element, $attrs) {
      $element.bind('touchend', onTouchEnd);

      function onTouchEnd(event) {
        var method = '$scope.' + $element.attr('ng-touchend');
        $scope.$apply(function () {
        eval(method);
        });
      };
    }
  };
});
aesopApp.directive('eventFocus', function(focus) {
  return function(scope, elem, attr) {
    elem.on(attr.eventFocus, function() {
      focus(attr.eventFocusId);
    });

    // Removes bound events in the element itself
    // when the scope is destroyed
    scope.$on('$destroy', function() {
      element.off(attr.eventFocus);
    });
  };
});

var makeBreadcrumbs = function($http, seriesID, season) {
  var breadcrumbs = [];

  if (!!seriesID) {
    var title = sessionStorage.getItem(seriesID);

    var addSeriesAndSeason = function() {
      breadcrumbs.push({
        url: '#/series/',
        display: 'TV Series',
      });
      breadcrumbs.push({
        url: '#/series/' + seriesID,
        display: title,
      });

      if (!!season) {
        breadcrumbs.push({
          url: '#/series/' + seriesID + '/' + season,
          display: 'Season ' + season,
        });
      }
    }

    if (title) {
      addSeriesAndSeason();
    } else {
      $http.get('/series/' + seriesID).success(function(data) {
        title = data.data.title;
        sessionStorage.setItem(seriesID, title);
        addSeriesAndSeason();
      });
    }
  }

  return breadcrumbs;
};

aesopApp.factory('Player', function($websocket, growl) {
  var Player;
  var socket = $websocket(wsPath('ws/remote/'));

  var reconnector;
  var reconnectWaitTime = 0.5;
  var reconnect = function() {
    growl.warning("Connection to server lost, reconnecting...", {ttl: 2000});
    var reconnector = setTimeout(function() {
      socket = $websocket(wsPath('ws/remote/'));
      socket.onOpen(function() {
        growl.success("Reconnected to server", {ttl: 2000});
        if (!!reconnector) {
          clearTimeout(reconnector);
          reconnector = null;
        }
      });
      socket.onClose(reconnect);
    }, reconnectWaitTime*1000);
  };
  socket.onClose(reconnect);

  var command = function(command, args) {
    socket.send(JSON.stringify({
      command: command,
      arguments: args || {},
    }));
  };

  Player = {
    setSubtitle: function(sid) {
      command('subtitle', {'sid': sid});
    },
    setAudio: function(aid) {
      command('audio', {'aid': aid});
    },
    play: function(videoID, videoType) {
      command('play', {
        id: videoID,
        type: videoType,
      });
    },
    queue: function(videoID, videoType) {
      command('queue', {
        id: videoID,
        type: videoType,
      });
    },
    playSeason: function(seriesID, seasonNumber) {
      command('play_season', {
        id: seriesID,
        season: seasonNumber,
      });
    },
    queueSeason: function(seriesID, seasonNumber) {
      command('queue_season', {
        id: seriesID,
        season: seasonNumber,
      });
    },
    setVolume: function(volume) { command('volume', { volume: volume }); },
    seekForward: function() { command('seek_forward'); },
    seekBack: function() { command('seek_backward'); },
    toggle: function() { command('toggle'); },
    previous: function() { command('previous'); },
    next: function() { command('next'); },
    stop: function() { command('stop'); },
  };

  return Player;
});

aesopApp.config(['$stateProvider', '$urlRouterProvider', function($stateProvider, $urlRouterProvider) {
  $stateProvider.
    state('settings', {
      url: '/settings/',
      templateUrl: '/static/templates/settings.html',
      controller: 'SettingsController'
    }).
    state('editMovie', {
      url: '/modify/movie/:movieID',
      templateUrl: '/static/templates/edit-movie.html',
      controller: 'EditMovieController'
    }).
    state('movies', {
      url: '/movies/',
      templateUrl: '/static/templates/media.html',
      controller: 'MovieController'
    }).
    state('seriesList', {
      url: '/series/',
      templateUrl: '/static/templates/serieslist.html',
      controller: 'SeriesListController'
    }).
    state('series', {
      url: '/series/:seriesID',
      templateUrl: '/static/templates/series.html',
      controller: 'SeriesController'
    }).
    state('season', {
      url: '/series/:seriesID/:season',
      templateUrl: '/static/templates/media.html',
      controller: 'SeasonController'
    }).
    state('player', {
      url: '/player/',
      templateUrl: '/static/templates/player.html',
      controller: 'PlayerController'
    });
  $urlRouterProvider.otherwise('/player/');
}]);

aesopApp.config(['growlProvider', function(growlProvider) {
  growlProvider.globalDisableIcons(true);
}]);

aesopApp.controller('MainController', function($scope, $state, Player, growl, $websocket) {
  $scope.mobileHidden = true;
  $scope.refresh = function() {
    $state.reload();
  };
  $scope.Player = Player;

  var socket = $websocket(wsPath('ws/events/'));

  var reconnector;
  var reconnectWaitTime = 0.5;
  var reconnect = function() {
    console.log('reconnecting in ' + reconnectWaitTime + ' seconds');
    var reconnector = setTimeout(function() {
      socket = $websocket(wsPath('ws/events/'));
      socket.onOpen(function() {
        console.log('successfully reconnected');
        if (!!reconnector) {
          clearTimeout(reconnector);
          reconnector = null;
        }
      });
      socket.onClose(reconnect);
      socket.onMessage(onMessage);
    }, reconnectWaitTime*1000);
  };
  socket.onClose(reconnect);
  socket.onMessage(onMessage);

  function onMessage(ev) {
    var j = JSON.parse(ev.data);

    if (j.type === 'player') {
      console.log(j);
      Player[j.attribute] = j.value;
      $scope.$digest();
    } else if (j.type === 'notification') {
      var icon = {
        'success': '<i class="fa fa-success"></i> ',
        'info': '<i class="fa fa-info"></i> ',
        'error': '<i class="fa fa-times"></i> ',
        'warning': '<i class="fa fa-exclamation"></i> ',
      }[j.level];

      var message = '';

      if (!!icon)
        message += icon;
      message += j.message;

      growl[j.level](message);
    }
  };
});

aesopApp.controller('EditMovieController', function($scope, $stateParams, $http, growl) {
  $scope.movieID = $stateParams.movieID;
  $scope.movie = {};
  $scope.selectedMovie = {};
  $scope.movieSuggestions = [];

  $scope.$watch('selectedMovie.selected', function(newValue, oldValue) {
    if (newValue !== oldValue && typeof(oldValue) !== 'undefined') {
      $scope.movie.title = newValue.title;
      $scope.movie.year = newValue.year;

      if (newValue.id !== $scope.movie.media_id) {
        getIMDBGenres(newValue.id);
      }

      $scope.movie.media_id = newValue.id;
    };
  });

  $http.get('/genres').success(function(data) {
    $scope.genres = data.genres;
  });

  $http.get('/movies/' + $scope.movieID).success(function(data) {
    $scope.movie = data.movie;
    $scope.selectedMovie.selected = data.movie;
  });

  var getIMDBGenres = function(i) {
    $scope.genresLoading = true;
    $http.get('/search/genres/', {
      params: {
        i: i,
        type: 'movie',
      }
    }).success(function(data) {
      $scope.movie.genres = data.genres;
      $scope.genresLoading = false;
    });
  };

  $scope.save = function() {
    // FIXME: make sure it's successful
    $http.post('/movies/' + $scope.movieID, {
      'movie': $scope.movie,
    }).success(function() {
      growl.success('<i class="fa fa-check"></i> Saved changes', {ttl: 2000});
    }).error(function() {
      growl.error('<i class="fa fa-times"></i> Error saving changes');
    });
  };

  $scope.getIMDBSuggestions = function(q) {
    $http.get('/search/', {
      params: {
        q: q,
        type: 'movie',
      }
    }).success(function(data) {
      $scope.movieSuggestions = data.results;
    });
  };
});

aesopApp.controller('SettingsController', function($scope, $http) {
  $scope.configuration = [];
  $scope.sources = [];
  $scope.stats = [];

  $scope.new_source_type = 'movies';

  $scope.removeSource = function(source) {
    var i = $scope.sources.indexOf(source);
    $scope.sources.splice(i, 1);
  };

  $scope.addNewSource = function() {
    $scope.sources.push({
      'type': $scope.new_source_type,
      'path': $scope.new_source_path,
    });

    $scope.new_source_type = 'movies';
    $scope.new_source_path = '';
  };

  $scope.save = function() {
    $http.post('/update/');
  };

  $scope.save = function() {
    var configuration = [];

    $scope.configuration.forEach(function(section) {
      section.values.forEach(function(c) {
        var value = c.value;
        if (!!c.typeahead) {
          value = c.value.value || c['default'];
        }

        var conf = {
          key: c.key,
          'value': value,
          section: c.section,
        };
        console.log(conf);
        configuration.push(conf);
      });
    });

    $http.post('/settings/', {
      'configuration': configuration,
      'sources': $scope.sources,
    });
  };

  $scope.source_types = {
    'anime': 'Anime',
    'movies': 'Movies',
    'tv': 'TV Shows',
  };
  $http.get('/settings/').success(function(data) {
    $scope.configuration = data.configuration;
    $scope.sources = data.sources;
  });
  $http.get('/stats/').success(function(data) {
    $scope.stats = data.stats;
  });
});

aesopApp.controller('MovieController', function($scope, $http, Player) {
  var url = '/movies';

  $scope.media_type = 'movie';
  $scope.media = [];
  $http.get(url).success(function(data) {
    $scope.media = data.data;
  });

  $scope.play = function(id) {
    Player.play(id, 'movie');
  };

  $scope.queue = function(id) {
    Player.queue(id, 'movie');
  };

  $scope.toggleWatched = function(videoID, video) {
    $http.post('/movies/setwatched/' + videoID).success(function(data) {
      video.watched = data.watched;
    });
  };
});

aesopApp.controller('SeriesListController', function($scope, $stateParams, $http) {
  $scope.seriesList = [];
  $http.get('/series').success(function(data) {
    $scope.seriesList = data.data;

    $scope.seriesList.forEach(function(f) {
      var title = f.title;
      var id = f.media_id;
      sessionStorage.setItem(id, title);
    });
  });

  $scope.breadcrumbs = [];
});

aesopApp.controller('SeriesController', function($scope, $stateParams, $http, Player) {
  $scope.seasons = [];
  $scope.media_id = $stateParams.seriesID;

  $scope.play = function(seasonNumber) {
    Player.playSeason($scope.media_id, seasonNumber);
  };

  $scope.queue = function(seasonNumber) {
    Player.queueSeason($scope.media_id, seasonNumber);
  };

  $http.get('/series/' + $scope.media_id + '/seasons').success(function(data) {
    $scope.seasons = data.data;
  });

  $scope.breadcrumbs = makeBreadcrumbs($http, $scope.media_id);
});

aesopApp.controller('SeasonController', function($scope, $http, $stateParams, Player) {
  $scope.media_type = 'series';
  $scope.media = [];
  $scope.media_id = $stateParams.seriesID;
  $scope.season = $stateParams.season;
  $scope.toggleWatched = function(videoID, video) {
    $http.post('/series/setwatched/' + videoID).success(function(data) {
      video.watched = data.watched;
    });
  };

  var url = '/series/' + $scope.media_id + '/episodes/' + $scope.season;
  $http.get(url).success(function(data) {
    $scope.media = data.data;
  });

  $scope.breadcrumbs = makeBreadcrumbs($http, $scope.media_id, $scope.season);

  $scope.play = function(id) {
    Player.play(id, 'tv');
  };

  $scope.queue = function(id) {
    Player.queue(id, 'tv');
  };

});

aesopApp.controller('PlayerController', function($scope, $timeout, Player) {
  $scope.Player = Player;

  var timer = null;

  $scope.$watch('Player.volume', function(newValue, oldValue) {
    if (newValue === oldValue || typeof(oldValue) === 'undefined') {
      return;
    }

    if (timer !== null) {
      $timeout.cancel(timer);
    }

    timer = $timeout(function() {
      Player.setVolume(newValue);
    }, 100);
  });

  $scope.changeSubtitles = function() {
      Player.setSubtitle(Player.selected_subtitle);
  };

  $scope.changeAudio = function() {
      Player.setAudio(Player.selected_audio);
  };
});

