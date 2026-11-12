import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'app.dart';
import 'config.dart';

void main() => runApp(CodeAtlasApp(apiBase: apiBase, httpClient: http.Client()));
