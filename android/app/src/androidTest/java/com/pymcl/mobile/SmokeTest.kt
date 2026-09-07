package com.pymcl.mobile

import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Rule
import org.junit.Test

class SmokeTest {
    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    @Test
    fun launchTabShows() {
        rule.onNodeWithText("PyMCL").assertIsDisplayed()
        rule.onNodeWithText("启动配置").assertIsDisplayed()
        rule.onAllNodesWithText("启动游戏")[0].assertIsDisplayed()
    }

    @Test
    fun bottomBarHasSixTabs() {
        listOf("启动", "实例", "联机", "下载", "AI", "设置").forEach { label ->
            rule.onNodeWithText(label).assertIsDisplayed()
        }
    }

    @Test
    fun downloadTabOpens() {
        rule.onNodeWithText("下载").performClick()
        rule.onNodeWithText("原版游戏").assertIsDisplayed()
        listOf("Mod", "整合包", "数据包", "资源包", "光影包", "下载任务").forEach { label ->
            rule.onNodeWithText(label).assertExists()
        }
    }

    @Test
    fun instanceTabOpens() {
        rule.onNodeWithText("实例").performClick()
        rule.onNodeWithText("新实例名").assertIsDisplayed()
    }
}
