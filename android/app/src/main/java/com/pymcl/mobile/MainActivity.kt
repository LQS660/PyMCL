package com.pymcl.mobile

import android.graphics.Color as AndroidColor
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.ui.AppScaffold
import com.pymcl.mobile.vm.AppViewModel

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.light(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT),
        )
        setContent {
            // 主题在 AppScaffold 里套：它要先读配置才知道用哪套配色，
            // 放外面就得在 Activity 层再读一次同一份设置。
            Surface(Modifier.fillMaxSize(), color = Color.Transparent) {
                AppScaffold(vm)
            }
        }
    }

    /**
     * 退到后台把攒着的设置写出去。
     *
     * 设置页的 DisposableEffect 只覆盖「用户自己退出那一页」；从设置页直接
     * 按 Home 是不走 onDispose 的，这里兜一手。
     */
    override fun onStop() {
        Settings.flushIfDirty()
        super.onStop()
    }
}
