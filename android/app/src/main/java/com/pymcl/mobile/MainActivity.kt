package com.pymcl.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.pymcl.mobile.model.GameInstance
import com.pymcl.mobile.model.LaunchPlan
import com.pymcl.mobile.model.VersionManifest
import com.pymcl.mobile.ui.AiScreen
import com.pymcl.mobile.ui.DownloadScreen
import com.pymcl.mobile.ui.InstancesScreen
import com.pymcl.mobile.ui.LaunchScreen
import com.pymcl.mobile.ui.MainTab
import com.pymcl.mobile.ui.MultiplayerScreen
import com.pymcl.mobile.ui.PyMclTheme
import com.pymcl.mobile.ui.SettingsScreen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val app by lazy { PyMclApp.get(application) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = PyMclTheme.Green,
                    onPrimary = Color.White,
                    secondary = PyMclTheme.GreenDeep,
                    background = PyMclTheme.Background,
                    onBackground = PyMclTheme.TextPrimary,
                ),
            ) {
                MainShell(
                    onLaunchGame = { startActivity(Intent(this, GameActivity::class.java)) },
                )
            }
        }
        lifecycleScope.launch {
            app.manifestRepo.readCached()
        }
    }

    @Composable
    private fun MainShell(onLaunchGame: () -> Unit) {
        val navController = rememberNavController()
        val scope = rememberCoroutineScope()
        val backStack by navController.currentBackStackEntryAsState()
        val currentRoute = backStack?.destination?.route ?: MainTab.Launch.route

        var instances by remember { mutableStateOf<List<GameInstance>>(emptyList()) }
        var manifest by remember { mutableStateOf<VersionManifest?>(null) }
        var launchPlan by remember { mutableStateOf<LaunchPlan?>(null) }
        val tasks by app.launchPlanner.tasks.collectAsState()
        val aiMessages by app.aiRepo.messages.collectAsState()

        LaunchedEffect(Unit) {
            instances = app.instanceStore.listInstances()
            manifest = app.manifestRepo.readCached()
            launchPlan = instances.firstOrNull()?.let { app.launchPlanner.planLaunch(it) }
        }

        Scaffold(
            bottomBar = {
                NavigationBar(containerColor = PyMclTheme.Background) {
                    MainTab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = PyMclTheme.Green,
                                selectedTextColor = PyMclTheme.Green,
                                indicatorColor = PyMclTheme.Green.copy(alpha = 0.12f),
                            ),
                        )
                    }
                }
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = MainTab.Launch.route,
                modifier = Modifier.padding(innerPadding),
            ) {
                composable(MainTab.Launch.route) {
                    LaunchScreen(
                        plan = launchPlan,
                        onLaunch = onLaunchGame,
                    )
                }
                composable(MainTab.Instances.route) {
                    InstancesScreen(instances = instances)
                }
                composable(MainTab.Multiplayer.route) {
                    MultiplayerScreen()
                }
                composable(MainTab.Download.route) {
                    DownloadScreen(
                        manifest = manifest,
                        tasks = tasks,
                        onRefreshManifest = {
                            scope.launch {
                                app.launchPlanner.enqueueDownload("版本清单")
                                app.manifestRepo.fetchManifest(forceRefresh = true)
                                    .onSuccess { manifest = it }
                            }
                        },
                    )
                }
                composable(MainTab.Ai.route) {
                    AiScreen(
                        messages = aiMessages,
                        onSend = { app.aiRepo.send(it) },
                    )
                }
                composable(MainTab.Settings.route) {
                    SettingsScreen()
                }
            }
        }
    }
}
