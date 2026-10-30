package com.modmind.ai

import android.content.ContentValues
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

private val Brown = Color(0xFF211812)
private val SurfaceBrown = Color(0xFF30231B)
private val Cream = Color(0xFFF4E5D5)
private val Accent = Color(0xFFD7A77B)

data class ModItem(val id: String, val title: String, val description: String, val downloads: Long)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("modmind", MODE_PRIVATE)
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Accent, onPrimary = Brown, background = Brown,
                    surface = SurfaceBrown, onSurface = Cream, onBackground = Cream
                )
            ) {
                ModMindScreen(
                    initialServer = prefs.getString("server", "") ?: "",
                    onSaveServer = { prefs.edit().putString("server", it).apply() },
                    onSaveZip = { bytes -> saveZip(bytes) }
                )
            }
        }
    }

    private fun saveZip(bytes: ByteArray): String {
        val resolver = contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, "ModMind-Pack.zip")
            put(MediaStore.Downloads.MIME_TYPE, "application/zip")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("Не удалось создать файл в Загрузках")
        resolver.openOutputStream(uri)?.use { it.write(bytes) }
            ?: error("Не удалось записать ZIP")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        }
        return "Архив сохранён в папку Загрузки: ModMind-Pack.zip"
    }
}

@Composable
private fun ModMindScreen(
    initialServer: String,
    onSaveServer: (String) -> Unit,
    onSaveZip: (ByteArray) -> String
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var server by remember { mutableStateOf(initialServer) }
    var showSettings by remember { mutableStateOf(initialServer.isBlank()) }
    var description by remember { mutableStateOf("") }
    var version by remember { mutableStateOf("1.21.1") }
    var loader by remember { mutableStateOf("fabric") }
    var mods by remember { mutableStateOf(listOf<ModItem>()) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var status by remember { mutableStateOf("Подключи адрес сервера Render в настройках, чтобы начать.") }
    var busy by remember { mutableStateOf(false) }
    var aiEnabled by remember { mutableStateOf(false) }

    fun runTask(block: suspend () -> Unit) {
        if (busy) return
        scope.launch {
            busy = true
            try { block() } catch (e: Exception) {
                status = "Ошибка: ${e.message ?: "не удалось выполнить запрос"}"
            } finally { busy = false }
        }
    }

    Surface(modifier = Modifier.fillMaxSize(), color = Brown) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Surface(color = Accent, shape = RoundedCornerShape(14.dp), modifier = Modifier.size(42.dp)) {
                        Box(contentAlignment = Alignment.Center) {
                            Text("M", color = Brown, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black)
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text("ModMind AI", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                        Text("Minecraft modpack creator", style = MaterialTheme.typography.labelSmall, color = Accent)
                    }
                }
                IconButton(onClick = { showSettings = !showSettings }) {
                    Icon(Icons.Default.Settings, contentDescription = "Настройки", tint = Cream)
                }
            }
            if (showSettings) {
                Card(colors = CardDefaults.cardColors(containerColor = SurfaceBrown), shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth().padding(top = 18.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Сервер Render", fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = server, onValueChange = { server = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("https://имя-сервиса.onrender.com") },
                            singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
                        )
                        Text("Вставь публичный URL своего сервиса Render без / в конце.", style = MaterialTheme.typography.bodySmall, color = Accent)
                        Button(onClick = {
                            server = server.trim().trimEnd('/')
                            onSaveServer(server)
                            showSettings = false
                            status = if (server.isNotBlank()) "Адрес сервера сохранён." else "Укажи адрес сервера Render."
                        }, modifier = Modifier.align(Alignment.End)) { Text("Сохранить") }
                    }
                }
            }
            Spacer(Modifier.height(22.dp))
            Text("Создай свой модпак", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("Опиши идею — ИИ найдёт подходящие моды в Modrinth.", color = Cream.copy(alpha = .7f), modifier = Modifier.padding(top = 6.dp, bottom = 16.dp))
            OutlinedTextField(
                value = description, onValueChange = { description = it.take(600) },
                modifier = Modifier.fillMaxWidth(), minLines = 3,
                label = { Text("Какой мир хочешь создать?") },
                placeholder = { Text("Например: магия, драконы, RPG и новые измерения…") }
            )
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                var versionExpanded by remember { mutableStateOf(false) }
                var loaderExpanded by remember { mutableStateOf(false) }
                Box(Modifier.weight(1f)) {
                    OutlinedButton(onClick = { versionExpanded = true }, modifier = Modifier.fillMaxWidth()) { Text(version) }
                    DropdownMenu(expanded = versionExpanded, onDismissRequest = { versionExpanded = false }) {
                        listOf("1.21.1", "1.20.1", "1.20.4", "1.19.2", "1.18.2").forEach {
                            DropdownMenuItem(text = { Text(it) }, onClick = { version = it; versionExpanded = false })
                        }
                    }
                }
                Box(Modifier.weight(1f)) {
                    OutlinedButton(onClick = { loaderExpanded = true }, modifier = Modifier.fillMaxWidth()) { Text(loader.replaceFirstChar { it.uppercase() }) }
                    DropdownMenu(expanded = loaderExpanded, onDismissRequest = { loaderExpanded = false }) {
                        listOf("fabric", "forge", "neoforge", "quilt").forEach {
                            DropdownMenuItem(text = { Text(it.replaceFirstChar { c -> c.uppercase() }) }, onClick = { loader = it; loaderExpanded = false })
                        }
                    }
                }
            }
            Button(
                onClick = {
                    runTask {
                        require(server.startsWith("https://")) { "Сначала укажи HTTPS-адрес Render в настройках." }
                        require(description.trim().length >= 4) { "Добавь чуть больше подробностей." }
                        status = "ИИ анализирует описание…"
                        val plan = apiRequest(server, "/api/plan", "POST", JSONObject().put("description", description.trim()).toString())
                        aiEnabled = plan.optBoolean("ai_enabled")
                        val queries = plan.optJSONArray("search_queries") ?: JSONArray()
                        val results = linkedMapOf<String, ModItem>()
                        for (i in 0 until minOf(queries.length(), 6)) {
                            val q = URLEncoder.encode(queries.getString(i), "UTF-8")
                            val path = "/api/search?query=$q&minecraft_version=${URLEncoder.encode(version, "UTF-8")}&loader=$loader&limit=10"
                            val data = apiRequest(server, path, "GET")
                            val array = data.optJSONArray("mods") ?: JSONArray()
                            for (j in 0 until array.length()) {
                                val item = array.getJSONObject(j)
                                val id = item.optString("id")
                                if (id.isNotBlank()) results[id] = ModItem(id, item.optString("title", id), item.optString("description"), item.optLong("downloads"))
                            }
                        }
                        mods = results.values.take(40)
                        selected = mods.map { it.id }.toSet()
                        status = plan.optString("message") + "\nНайдено модов: ${mods.size}. Отметь те, которые хочешь добавить."
                    }
                },
                enabled = !busy, modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Brown)
            ) { Text(if (busy) "Подожди…" else "✦  Подобрать моды с ИИ", fontWeight = FontWeight.Bold) }
            if (mods.isNotEmpty()) {
                Spacer(Modifier.height(16.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Найденные моды", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("${selected.size} выбрано", color = Accent)
                }
                LazyColumn(Modifier.weight(1f).padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(mods, key = { it.id }) { mod ->
                        Card(colors = CardDefaults.cardColors(containerColor = SurfaceBrown), shape = RoundedCornerShape(16.dp)) {
                            Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = mod.id in selected, onCheckedChange = { checked ->
                                    selected = if (checked) selected + mod.id else selected - mod.id
                                })
                                Column(Modifier.weight(1f)) {
                                    Text(mod.title, fontWeight = FontWeight.SemiBold)
                                    Text(mod.description, style = MaterialTheme.typography.bodySmall, color = Cream.copy(alpha = .65f), maxLines = 2)
                                }
                            }
                        }
                    }
                }
                Button(
                    onClick = {
                        runTask {
                            require(selected.isNotEmpty()) { "Выбери хотя бы один мод." }
                            status = "Сервер скачивает моды и собирает ZIP…"
                            val body = JSONObject()
                                .put("name", "ModMind-Pack")
                                .put("minecraft_version", version)
                                .put("loader", loader)
                                .put("project_ids", JSONArray(selected.toList()))
                            val bytes = apiDownload(server, "/api/build", body.toString())
                            status = withContext(Dispatchers.IO) { onSaveZip(bytes) }
                        }
                    },
                    enabled = !busy, modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Brown)
                ) { Text("Собрать и скачать ZIP · ${selected.size}") }
            } else {
                Spacer(Modifier.weight(1f))
            }
            Text(status, color = Accent, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 12.dp))
            Text(if (aiEnabled) "Gemini AI подключён" else "Gemini / резервный поиск", color = Cream.copy(alpha = .45f), style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

private suspend fun apiRequest(base: String, path: String, method: String, body: String? = null): JSONObject =
    withContext(Dispatchers.IO) {
        val connection = (URL(base.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 20000
            readTimeout = 90000
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
        }
        try {
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) error("HTTP $code: $text")
            JSONObject(text)
        } finally { connection.disconnect() }
    }

private suspend fun apiDownload(base: String, path: String, body: String): ByteArray =
    withContext(Dispatchers.IO) {
        val connection = (URL(base.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 20000
            readTimeout = 180000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/zip")
            outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        try {
            val code = connection.responseCode
            if (code !in 200..299) {
                val message = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                error("HTTP $code: $message")
            }
            connection.inputStream.use { it.readBytes() }
        } finally { connection.disconnect() }
    }
